"""Erteilte US-Patente je Firma: laufend aus dem Amtsblatt des USPTO (Official Gazette for Patents), die Historie
aus den Sammeldateien von PatentsView.

Das Amtsblatt erscheint jeden Dienstag, dem Tag der Erteilung, und führt ein Verzeichnis der Patentinhaber. Es ist
ohne Anmeldung abrufbar, hält aber nur die letzten 52 Ausgaben vor (der Ordner einer Kalenderwoche wird im Folgejahr
überschrieben). Die Sammeldateien von PatentsView (alle Patente seit 1976, vierteljährlich) liegen seit 06/2026
hinter einer Anmeldung; sie werden von Hand geladen und mit ``--patente-ordner`` eingelesen. Soweit sie reichen,
ersetzen sie das Amtsblatt.

Im Verzeichnis steht jedes Patent beim ersten Erfinder („Erfinder; Miterfinder; and Mitinhaber, to Inhaber Titel
Nummer“) und unter jedem weiteren Erfinder und jedem Inhaber als Verweis („Name: See--“). Inhaber ist ein
Verweisname, der im Eintrag des ersten Erfinders hinter „to“ steht oder keine Person („Nachname, Vorname“) ist.

  patente_erteilt__<jahr>    tag, nummer, art (utility, design, plant, reissue, sonstige), inhaber
  patente_ausgaben__alle     Ausgabetage mit Zahl der Patente, Herkunft (amtsblatt, patentsview) und Lesart
  patente_zuordnung__alle    inhaber -> cik, konfidenz, art, gilt_ab, gilt_bis
"""
from __future__ import annotations

import html
import re
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from ..kern.ablage import Ablage
from ..kern.http import Abruf, QuelleNichtErreichbar
from ..kern.namen import RECHTSFORM, Namensabgleich, bereinige, trefferquote
from ..kern.schema import Parameter, als_parameter, leer, registriere
from ..kern.zeit import ET, handelbar_ab
from ..kern.zustand import Zeitbudget, merke_fortsetzung

SEITE = "https://www.uspto.gov/learning-and-resources/official-gazette/official-gazette-patents"
SEITE_HISTORIE = "https://data.uspto.gov/bulkdata/datasets/pvgpatdis"
ADRESSE = "https://patentsgazette.uspto.gov/week{woche:02d}/OG/{seite}"
SEITENLISTE = "patenteeByNameLeft.html"
SEITEN_ERSATZ = [f"patentee/alpha{b}.html" for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"] + ["patentee/alphaOthers.html"]
WOCHEN = 52
MIN_PATENTE = 2000             # eine Ausgabe mit weniger Patenten gilt als falsch gelesen (üblich sind 6.000 bis 9.000)
MINDEST_KONFIDENZ = 0.90
LESART = 2                     # Fassung des Leseverfahrens; Ausgaben einer älteren Fassung werden neu gelesen
PARAMETER_AB = pd.Timestamp("2001-01-01")      # der Handelskalender (kern/zeit.py) kennt die Schließungen ab 2001
# Nachprüfungsbescheide (reexamination certificates) stehen im Verzeichnis unter der alten Patentnummer; sie liegt
# um mehr als diesen Abstand unter der höchsten Nummer der Ausgabe
ABSTAND_NACHPRUEFUNG = {"": 100_000, "D": 100_000}
ABSTAND_NACHPRUEFUNG_SONST = 3_000
HERKUNFT_AMTSBLATT, HERKUNFT_PATENTSVIEW = "amtsblatt", "patentsview"
DATEI_PATENT = "g_patent"
# Inhaber wie auf der Patentschrift gedruckt; ersatzweise die von PatentsView vereinheitlichten Namen
DATEIEN_INHABER = (("g_assignee_not_disambiguated", "raw_assignee_organization"),
                   ("g_assignee_disambiguated", "disambig_assignee_organization"))
TABELLE_ERTEILT, TABELLE_AUSGABEN, TABELLE_ZUORDNUNG = "patente_erteilt", "patente_ausgaben", "patente_zuordnung"
SPALTEN_ERTEILT = ["tag", "nummer", "art", "inhaber"]
NUMMER = re.compile(r"^([A-Z]*)0*(\d+)$")
MUSTER_NUMMER = r"^(?P<v>[A-Z]{0,3})0*(?P<z>[0-9]{1,9})$"       # dasselbe für den Leser der Sammeldateien
ARTEN_PV = ["utility", "design", "plant", "reissue", "sonstige"]   # Arten in PatentsView; alles Übrige ist „sonstige“
# Rechtsformen hinter dem letzten Komma eines Namens („Baby Trend, Inc.“); „The“ für „Boeing Company, The“
FORMEN = RECHTSFORM | {"SAS", "SARL", "SRL", "SPA", "KG", "KGAA", "OY", "OYJ", "AB", "AS", "ASA", "KK", "GK", "PTE", "PTY",
                       "PC", "PLLC", "LLLP", "ULC", "SL", "APS", "NA", "BHD", "SRO", "LDA", "PUBL", "THE"}
EINTRAG = re.compile(r'<div class="list_item([12])">(.*?)</div>', re.S)
VERWEIS = re.compile(r'<a href="[^"]*?/US([A-Z]*\d+)-(\d{8})\.html">')
SEITENVERWEIS = re.compile(r'href="(patentee/alpha\w+\.html)"')
AUSGABETAG = re.compile(r"ISSUED ON THE (\d{1,2})\w* DAY OF ([A-Za-z]+), (\d{4})")
MARKE = re.compile(r"<[^>]+>")
LEERRAUM = re.compile(r"\s+")
ZU = re.compile(r"[;,] to ")
OHNE_ZEICHEN = re.compile(r"[^A-Z0-9]+")
SIEHE = ": See--"
ARTEN = {"": "utility", "D": "design", "PP": "plant", "RE": "reissue"}
MONATE = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november "
                                         "december".split())}
# Patente hält oft eine Tochter mit eigenem Namen. Inhaber (wie gedruckt) -> Name der börsennotierten Mutter bei EDGAR
# (die CIK, wenn der Name dort mehrdeutig ist).
# Von Hand geprüft, Stand 11/2026. Wann ein Inhaber zu einer anderen Mutter gehörte, steht in TOCHTER_FRUEHER.
TOCHTER_NAMEN = {
    "Dell Products L.P.": "Dell Technologies Inc.", "Microsoft Technology Licensing, LLC": "MICROSOFT CORP",
    "Cisco Technology, Inc.": "CISCO SYSTEMS, INC.", "Amazon Technologies, Inc.": "AMAZON COM INC",
    "Zoox, Inc.": "AMAZON COM INC", "Google LLC": "Alphabet Inc.", "Waymo LLC": "Alphabet Inc.",
    "Hewlett Packard Enterprise Development LP": "Hewlett Packard Enterprise Co",
    "Hewlett-Packard Development Company, L.P.": "HP INC", "Capital One Services, LLC": "CAPITAL ONE FINANCIAL CORP",
    "GM Global Technology Operations LLC": "General Motors Co", "Ford Global Technologies, LLC": "FORD MOTOR CO",
    "GE Precision Healthcare LLC": "GE HealthCare Technologies Inc.", "Intel Products IP LLC": "INTEL CORP",
    "Verizon Patent and Licensing Inc.": "VERIZON COMMUNICATIONS INC", "T-Mobile Innovations LLC": "T-Mobile US, Inc.",
    "T-Mobile USA, Inc.": "T-Mobile US, Inc.", "Boston Scientific Scimed, Inc.": "BOSTON SCIENTIFIC CORP",
    "Cardiac Pacemakers, Inc.": "BOSTON SCIENTIFIC CORP", "Covidien LP": "Medtronic plc",
    "Medtronic MiniMed, Inc.": "Medtronic plc", "Warsaw Orthopedic, Inc.": "Medtronic plc",
    "Pratt & Whitney Canada Corp.": "RTX Corp", "Hamilton Sundstrand Corporation": "RTX Corp",
    "Raytheon Company": "RTX Corp", "Goodrich Corporation": "RTX Corp", "Rosemount Aerospace Inc.": "RTX Corp",
    "Rockwell Collins, Inc.": "RTX Corp", "Halliburton Energy Services, Inc.": "HALLIBURTON CO",
    "Truist Bank": "TRUIST FINANCIAL CORP", "AT&T Intellectual Property I, L.P.": "AT&T INC.",
    "Wells Fargo Bank, N.A.": "WELLS FARGO & COMPANY/MN", "3M Innovative Properties Company": "3M CO",
    "Eaton Intelligent Power Limited": "Eaton Corp plc", "Aptiv Technologies AG": "Aptiv PLC",
    "InterDigital Patent Holdings, Inc.": "InterDigital, Inc.",
    "Rockwell Automation Technologies, Inc.": "ROCKWELL AUTOMATION, INC", "II-VI Delaware, Inc.": "COHERENT CORP.",
    "Aurora Operations, Inc.": "Aurora Innovation, Inc.", "Cilag GmbH International": "JOHNSON & JOHNSON",
    "Ethicon LLC": "JOHNSON & JOHNSON", "Avago Technologies International Sales Pte. Limited": "Broadcom Inc.",
    "VMware LLC": "Broadcom Inc.", "Schlumberger Technology Corporation": "SCHLUMBERGER LIMITED/NV",
    "Intuitive Surgical Operations, Inc.": "INTUITIVE SURGICAL INC", "Pacesetter, Inc.": "ABBOTT LABORATORIES",
    "Abbott Diabetes Care Inc.": "ABBOTT LABORATORIES", "Abbott Cardiovascular Systems Inc.": "ABBOTT LABORATORIES",
    "ResMed Pty Ltd": "RESMED INC", "Meta Platforms Technologies, LLC": "Meta Platforms, Inc.",
    "Western Digital Technologies, Inc.": "WESTERN DIGITAL CORP", "Sandisk Technologies, Inc.": "Sandisk Corp",
    "JPMorgan Chase Bank, N.A.": "JPMORGAN CHASE & CO", "Visa International Service Association": "VISA INC.",
    "Dolby Laboratories Licensing Corporation": "Dolby Laboratories, Inc.",
    "Rivian IP Holdings, LLC": "Rivian Automotive, Inc. / DE", "GlobalFoundries U.S. Inc.": "GLOBALFOUNDRIES Inc.",
    "Chevron U.S.A. Inc.": "CHEVRON CORP", "ExxonMobil Technology and Engineering Company": "EXXON MOBIL CORP",
    "Baker Hughes Oilfield Operations LLC": "Baker Hughes Co", "Disney Enterprises, Inc.": "Walt Disney Co",
    "Marvell Asia Pte Ltd": "Marvell Technology, Inc.", "Merck Sharp & Dohme LLC": "Merck & Co., Inc.",
    "Zimmer, Inc.": "ZIMMER BIOMET HOLDINGS, INC.", "Biomet Manufacturing, LLC": "ZIMMER BIOMET HOLDINGS, INC.",
    "Otis Elevator Company": "Otis Worldwide Corp", "Rosemount Inc.": "EMERSON ELECTRIC CO",
    "Fisher-Rosemount Systems, Inc.": "EMERSON ELECTRIC CO", "Dow Global Technologies LLC": "DOW INC.",
    "Lumentum Operations LLC": "Lumentum Holdings Inc.", "Walmart Apollo, LLC": "Walmart Inc.",
    "Target Brands, Inc.": "TARGET CORP", "Textron Innovations Inc.": "TEXTRON INC", "Bell Textron Inc.": "TEXTRON INC",
    "Garmin Switzerland GmbH": "GARMIN LTD", "Trane International Inc.": "Trane Technologies plc",
    "Johnson Controls Tyco IP Holdings LLP": "Johnson Controls International plc",
    "TE Connectivity Solutions GmbH": "TE Connectivity plc",
    "Semiconductor Components Industries, LLC": "ON SEMICONDUCTOR CORP", "NXP USA, Inc.": "NXP Semiconductors N.V.",
    "NXP B.V.": "NXP Semiconductors N.V.", "Qorvo US, Inc.": "Qorvo, Inc.",
    "QuantumScape Battery, Inc.": "QuantumScape Corp", "Harley-Davidson Motor Company, Inc.": "HARLEY-DAVIDSON, INC.",
    "Life Technologies Corporation": "THERMO FISHER SCIENTIFIC INC.", "ModernaTX, Inc.": "Moderna, Inc.",
    "Biogen MA Inc.": "BIOGEN INC.", "Northrop Grumman Systems Corporation": "NORTHROP GRUMMAN CORP /DE/",
    "Analog Devices International Unlimited Company": "ANALOG DEVICES INC", "Adeia Guides Inc.": "Adeia Inc.",
    "Activision Publishing, Inc.": "MICROSOFT CORP", "Nuance Communications, Inc.": "MICROSOFT CORP",
    "Toyota Jidosha Kabushiki Kaisha": "TOYOTA MOTOR CORP/",
    "Telefonaktiebolaget LM Ericsson (publ)": "ERICSSON LM TELEPHONE CO", "Nokia Technologies Oy": "NOKIA CORP",
    "ASML Netherlands B.V.": "ASML HOLDING NV", "Stryker European Operations Limited": "STRYKER CORP",
    "CNH Industrial America LLC": "CNH Industrial N.V.", "Universal City Studios LLC": "COMCAST CORP",
    "Comcast Cable Communications, LLC": "COMCAST CORP",
    "Charter Communications Operating, LLC": "CHARTER COMMUNICATIONS, INC. /MO/", "DISH Network L.L.C.": "EchoStar CORP",
    "DISH Network Technologies India Private Limited": "EchoStar CORP",
    "Home Depot Product Authority, LLC": "HOME DEPOT, INC.",
    # ergänzt nach dem ersten echten Lauf (größte nicht zugeordnete Inhaber aus 52 Ausgaben)
    "SharkNinja Operating LLC": "SharkNinja, Inc.", "Philip Morris Products S.A.": "Philip Morris International Inc.",
    "Nicoventures Trading Limited": "British American Tobacco p.l.c.",
    "Tyco Fire & Security GmbH": "Johnson Controls International plc",
    "Biosense Webster (Israel) Ltd.": "JOHNSON & JOHNSON", "DePuy Synthes Products, Inc.": "JOHNSON & JOHNSON",
    "Auris Health, Inc.": "JOHNSON & JOHNSON", "GM Cruise Holdings LLC": "General Motors Co",
    "Altria Client Services LLC": "ALTRIA GROUP, INC.", "GE Vernova Infrastructure Technology LLC": "GE Vernova Inc.",
    "Wolverine Outdoors, Inc.": "WOLVERINE WORLD WIDE INC /DE/", "LNW Gaming, Inc.": "Light & Wonder, Inc.",
    "Accenture Global Solutions Limited": "Accenture plc", "Universal Display Corporation": "UNIVERSAL DISPLAY CORP \\PA\\",
    "Solventum Intellectual Properties Company": "Solventum Corp",
    "BAE Systems Information and Electronic Systems Integration Inc.": "BAE SYSTEMS PLC /FI/",
    "Transportation IP Holdings, LLC": "WESTINGHOUSE AIR BRAKE TECHNOLOGIES CORP", "Conopco, Inc.": "UNILEVER PLC",
    "ATI Technologies ULC": "ADVANCED MICRO DEVICES INC", "Peridot Print LLC": "HP INC",
    "CareFusion 303, Inc.": "BECTON DICKINSON & CO", "Bard Access Systems, Inc.": "BECTON DICKINSON & CO",
    "Magna Electronics Inc.": "MAGNA INTERNATIONAL INC", "YETI Coolers, LLC": "YETI Holdings, Inc.",
    "DISH Wireless L.L.C.": "EchoStar CORP", "Boost SubscriberCo L.L.C.": "EchoStar CORP",
    "Morgan Stanley Services Group Inc.": "MORGAN STANLEY", "ExxonMobil Chemical Patents Inc.": "EXXON MOBIL CORP",
    "Corning Research & Development Corporation": "CORNING INC /NY", "InterDigital VC Holdings, Inc.": "InterDigital, Inc.",
    "St. Jude Medical, Cardiology Division, Inc.": "ABBOTT LABORATORIES", "Howmedica Osteonics Corp.": "STRYKER CORP",
    "Graphic Packaging International, LLC": "GRAPHIC PACKAGING HOLDING CO",
    "Logitech Europe S.A.": "LOGITECH INTERNATIONAL S.A.", "QUALCOMM Incorproated": "QUALCOMM INC/DE",
    "Sony Interactive Entertainment Inc.": "Sony Group Corp", "Sony Semiconductor Solutions Corporation": "Sony Group Corp",
    "Nokia Solutions and Networks Oy": "NOKIA CORP", "STMicroelectronics S.r.l.": "STMicroelectronics N.V.",
    # ergänzt für die Historie (große Inhaber seit 2001, die übernommen oder umgegründet wurden)
    "Xilinx, Inc.": "ADVANCED MICRO DEVICES INC", "Maxim Integrated Products, Inc.": "ANALOG DEVICES INC",
    "Linear Technology Corporation": "ANALOG DEVICES INC", "EMC IP Holding Company LLC": "Dell Technologies Inc.",
    "EMC Corporation": "Dell Technologies Inc.", "Google Technology Holdings LLC": "Alphabet Inc.",
    "DeepMind Technologies Limited": "Alphabet Inc.", "X Development LLC": "Alphabet Inc.",
    "Verily Life Sciences LLC": "Alphabet Inc.", "Facebook Technologies, LLC": "Meta Platforms, Inc.",
    "Oculus VR, LLC": "Meta Platforms, Inc.", "LinkedIn Corporation": "MICROSOFT CORP",
    "Red Hat, Inc.": "INTERNATIONAL BUSINESS MACHINES CORP", "Kyndryl, Inc.": "Kyndryl Holdings, Inc.",
    "Oracle America, Inc.": "ORACLE CORP", "Sun Microsystems, Inc.": "ORACLE CORP",
    "Cerner Innovation, Inc.": "ORACLE CORP", "Mobileye Vision Technologies Ltd.": "Mobileye Global Inc.",
    "National Semiconductor Corporation": "TEXAS INSTRUMENTS INC", "Broadcom Corporation": "Broadcom Inc.",
    "Avago Technologies General IP (Singapore) Pte. Ltd.": "Broadcom Inc.", "LSI Corporation": "Broadcom Inc.",
    "CA, Inc.": "Broadcom Inc.", "Mellanox Technologies, Ltd.": "NVIDIA CORP", "Novellus Systems, Inc.": "LAM RESEARCH CORP",
    "Varian Semiconductor Equipment Associates, Inc.": "APPLIED MATERIALS INC /DE",
    "Atmel Corporation": "MICROCHIP TECHNOLOGY INC", "Microsemi Corporation": "MICROCHIP TECHNOLOGY INC",
    "Freescale Semiconductor, Inc.": "NXP Semiconductors N.V.", "Marvell International Ltd.": "Marvell Technology, Inc.",
    "HGST Netherlands B.V.": "WESTERN DIGITAL CORP", "SanDisk Corporation": "Sandisk Corp",
    "Baker Hughes Incorporated": "Baker Hughes Co", "Smith International, Inc.": "SCHLUMBERGER LIMITED/NV",
    "Cameron International Corporation": "SCHLUMBERGER LIMITED/NV", "Medtronic, Inc.": "Medtronic plc",
    "Eaton Corporation": "Eaton Corp plc", "Carrier Corporation": "CARRIER GLOBAL Corp",
    "Sikorsky Aircraft Corporation": "LOCKHEED MARTIN CORP", "Dow Silicones Corporation": "DOW INC.",
    "Pioneer Hi-Bred International, Inc.": "Corteva, Inc.", "The Gillette Company LLC": "PROCTER & GAMBLE Co",
    "PayPal, Inc.": "PayPal Holdings, Inc.", "UATC, LLC": "Aurora Innovation, Inc.",
    "Xerox Corporation": "Xerox Holdings Corp",
    # ergänzt nach dem Probelauf der Historie (größte Inhaber ohne Treffer oder bei einer Firma ohne Börsenkürzel)
    "E. I. du Pont de Nemours and Company": "Corteva, Inc.",
    "Toyota Motor Engineering & Manufacturing North America, Inc.": "TOYOTA MOTOR CORP/",
    "Nortel Networks Limited": 72911, "Baker Hughes Holdings LLC": "Baker Hughes Co",
    "Delphi Technologies, Inc.": "Aptiv PLC", "Delphi Technologies IP Limited": "BORGWARNER INC",
    "Alcatel Lucent": "NOKIA CORP", "Alcatel-Lucent USA Inc.": "NOKIA CORP", "Lucent Technologies Inc.": "NOKIA CORP",
    "Juniper Networks, Inc.": "Hewlett Packard Enterprise Co", "Shell Oil Company": "Shell plc",
    "Black & Decker Inc.": "STANLEY BLACK & DECKER, INC.",
}
TOCHTER = {bereinige(tochter): mutter for tochter, mutter in TOCHTER_NAMEN.items()}
# Frühere Zugehörigkeit eines Inhabers: (bis zu diesem Tag, Mutter bis dahin), aufsteigend; danach gilt TOCHTER_NAMEN
# und ohne Eintrag dort der Inhaber selbst. Mutter: Name bei EDGAR, die CIK (wenn der Name dort mehrdeutig ist oder
# heute anders lautet) oder None = der Inhaber selbst über den Namensabgleich (er war eigenständig oder nicht börsennotiert).
# Stichtag ist der Vollzug der Übernahme, Abspaltung oder Umgründung. Von Hand geprüft, Stand 11/2026.
TOCHTER_FRUEHER = {
    "Dell Products L.P.": [("2013-10-29", 826083)], "Zoox, Inc.": [("2020-06-26", None)],
    "Google LLC": [("2015-10-02", 1288776)], "Google Technology Holdings LLC": [("2015-10-02", 1288776)],
    "DeepMind Technologies Limited": [("2015-10-02", 1288776)],
    "GM Global Technology Operations LLC": [("2009-07-10", 40730)],
    "GE Precision Healthcare LLC": [("2023-01-04", "GENERAL ELECTRIC CO")],
    "GE Vernova Infrastructure Technology LLC": [("2024-04-02", "GENERAL ELECTRIC CO")],
    "T-Mobile USA, Inc.": [("2013-05-01", "DEUTSCHE TELEKOM AG")],
    "Cardiac Pacemakers, Inc.": [("1994-12-13", "ELI LILLY & Co"), ("2006-04-21", "GUIDANT CORP")],
    "Covidien LP": [("2015-01-26", 1385187)], "Medtronic MiniMed, Inc.": [("2015-01-26", 64670)],
    "Warsaw Orthopedic, Inc.": [("2015-01-26", 64670)], "Medtronic, Inc.": [("2015-01-26", 64670)],
    "Raytheon Company": [("2020-04-03", 1047122)], "Goodrich Corporation": [("2012-07-26", 42542)],
    "Rosemount Aerospace Inc.": [("2012-07-26", 42542)], "Rockwell Collins, Inc.": [("2018-11-26", None)],
    "Otis Elevator Company": [("2020-04-03", "RTX Corp")], "Carrier Corporation": [("2020-04-03", "RTX Corp")],
    "Sikorsky Aircraft Corporation": [("2015-11-06", "RTX Corp")], "Aurora Operations, Inc.": [("2021-11-03", None)],
    "UATC, LLC": [("2021-01-19", "Uber Technologies, Inc"), ("2021-11-03", None)],
    "VMware LLC": [("2023-11-22", 1124610)],
    "Pacesetter, Inc.": [("1994-09-30", None), ("2017-01-04", "ST JUDE MEDICAL INC")],
    "St. Jude Medical, Cardiology Division, Inc.": [("2017-01-04", "ST JUDE MEDICAL INC")],
    "Sandisk Technologies, Inc.": [("2016-05-12", 1000180), ("2025-02-24", "WESTERN DIGITAL CORP")],
    "SanDisk Corporation": [("2016-05-12", 1000180), ("2025-02-24", "WESTERN DIGITAL CORP")],
    "HGST Netherlands B.V.": [("2012-03-08", None)],
    "Baker Hughes Oilfield Operations LLC": [("2017-07-03", 808362)], "Baker Hughes Incorporated": [("2017-07-03", 808362)],
    "Smith International, Inc.": [("2010-08-27", None)], "Cameron International Corporation": [("2016-04-01", 941548)],
    "Disney Enterprises, Inc.": [("2019-03-20", 1001039)], "Marvell Asia Pte Ltd": [("2021-04-20", 1058057)],
    "Marvell International Ltd.": [("2021-04-20", 1058057)], "Merck Sharp & Dohme LLC": [("2009-11-03", 64978)],
    "Zimmer, Inc.": [("2001-08-06", "BRISTOL MYERS SQUIBB CO")], "Biomet Manufacturing, LLC": [("2015-06-24", None)],
    "Dow Global Technologies LLC": [("2017-09-01", 29915), ("2019-04-02", 1666700)],
    "Dow Silicones Corporation": [("2019-04-02", 1666700)],
    "Pioneer Hi-Bred International, Inc.": [("2017-09-01", 30554), ("2019-06-03", 1666700)],
    "Monsanto Technology LLC": [("2018-06-07", "MONSANTO CO /NEW/")],
    "Trane International Inc.": [("2008-06-05", None)], "Life Technologies Corporation": [("2014-02-03", 1073431)],
    "Activision Publishing, Inc.": [("2023-10-13", "Activision Blizzard, Inc.")],
    "Nuance Communications, Inc.": [("2022-03-04", 1002517)], "LinkedIn Corporation": [("2016-12-08", None)],
    "Red Hat, Inc.": [("2019-07-09", None)], "Sun Microsystems, Inc.": [("2010-01-27", None)],
    "Cerner Innovation, Inc.": [("2022-06-08", "CERNER CORP /MO/")],
    "Mobileye Vision Technologies Ltd.": [("2014-08-01", None), ("2017-08-08", "Mobileye N.V."), ("2022-10-26", "INTEL CORP")],
    "National Semiconductor Corporation": [("2011-09-23", None)],
    "Broadcom Corporation": [("2016-02-01", 1054374), ("2018-04-04", 1649338)],
    "Avago Technologies General IP (Singapore) Pte. Ltd.": [("2016-02-01", 1441634), ("2018-04-04", 1649338)],
    "LSI Corporation": [("2014-05-06", None), ("2016-02-01", 1441634), ("2018-04-04", 1649338)],
    "CA, Inc.": [("2018-11-05", None)], "Mellanox Technologies, Ltd.": [("2020-04-27", None)],
    "Novellus Systems, Inc.": [("2012-06-04", None)],
    "Varian Semiconductor Equipment Associates, Inc.": [("2011-11-10", None)],
    "Atmel Corporation": [("2016-04-04", None)], "Microsemi Corporation": [("2018-05-29", None)],
    "Freescale Semiconductor, Inc.": [("2006-12-01", 1272547), ("2015-12-07", 1392522)], "Xilinx, Inc.": [("2022-02-14", None)],
    "Maxim Integrated Products, Inc.": [("2021-08-26", None)], "Linear Technology Corporation": [("2017-03-10", None)],
    "EMC Corporation": [("2016-09-07", None)], "Eaton Corporation": [("2012-11-30", 31277)],
    "CNH Industrial America LLC": [("2013-09-30", "CNH GLOBAL N V")],
    "Universal City Studios LLC": [("2004-05-12", None), ("2011-01-28", "GENERAL ELECTRIC CO")],
    "DISH Network L.L.C.": [("2023-12-31", 1001082)], "DISH Wireless L.L.C.": [("2023-12-31", 1001082)],
    "DISH Network Technologies India Private Limited": [("2023-12-31", 1001082)],
    "SharkNinja Operating LLC": [("2023-07-31", None)],
    "Philip Morris Products S.A.": [("2008-03-28", "ALTRIA GROUP, INC.")], "Auris Health, Inc.": [("2019-04-01", None)],
    "QuantumScape Battery, Inc.": [("2020-11-25", None)], "ATI Technologies ULC": [("2006-10-25", None)],
    "CareFusion 303, Inc.": [("2015-03-17", "CareFusion Corp")], "Bard Access Systems, Inc.": [("2017-12-29", "BARD C R INC /NJ/")],
    "The Gillette Company LLC": [("2005-10-01", None)],
    "PayPal, Inc.": [("2002-10-03", None), ("2015-07-20", "EBAY INC")], "Xerox Corporation": [("2019-07-31", 108772)],
    "E. I. du Pont de Nemours and Company": [("2017-09-01", 30554), ("2019-06-03", 1666700)],
    "Delphi Technologies, Inc.": [("2009-10-06", 1072342)], "Delphi Technologies IP Limited": [("2020-10-02", 1707092)],
    "Alcatel Lucent": [("2016-01-14", 886125)], "Alcatel-Lucent USA Inc.": [("2016-01-14", 886125)],
    "Lucent Technologies Inc.": [("2006-11-30", 1006240), ("2016-01-14", 886125)],
    "Juniper Networks, Inc.": [("2025-07-02", 1043604)], "Black & Decker Inc.": [("2010-03-12", 12355)],
    "IGT": [("2015-04-07", 353944), ("2025-07-01", 1619762)],
    "Altera Corporation": [("2015-12-28", 768251), ("2025-09-12", "INTEL CORP")],
}


def _stufen() -> dict[str, list[tuple[pd.Timestamp | None, pd.Timestamp | None, str | int | None]]]:
    """Je Inhaber (bereinigt) die Zeiträume (gilt_ab, gilt_bis, Mutter) in zeitlicher Folge."""
    stufen = {schluessel: [(None, None, mutter)] for schluessel, mutter in TOCHTER.items()}
    for tochter, frueher in TOCHTER_FRUEHER.items():
        schluessel = bereinige(tochter)
        grenzen = [pd.Timestamp(bis) for bis, _ in frueher]
        if grenzen != sorted(grenzen):
            raise ValueError(f"TOCHTER_FRUEHER nicht aufsteigend: {tochter}")
        muetter = [m for _, m in frueher] + [TOCHTER.get(schluessel)]
        stufen[schluessel] = list(zip([None] + grenzen, grenzen + [None], muetter))
    return stufen


STUFEN = _stufen()

_OFFEN = "amtlich offen: 35 U.S.C. 153; das Amtsblatt erscheint am Tag der Erteilung (jeder Dienstag)"
registriere(Parameter(
    id="GA1-01", name="Erteilte Patente",
    definition="Zahl der an einem Ausgabetag an die Firma und ihre bekannten Patent-Töchter erteilten Erfindungspatente "
               "(utility). Ein Patent mit mehreren Inhabern zählt bei jedem. Wochen ohne Zeile zählen null; das "
               "Verhältnis zum F&E-Aufwand (Katalog: Innovationseffizienz) bildet der Nutzer",
    einheit="Anzahl", frequenz="wöchentlich (Dienstag)", offenlegung=_OFFEN, quelle=f"{SEITE}; Historie: {SEITE_HISTORIE}",
    lizenz="gemeinfrei (US-Behörde); Historie aus PatentsView (USPTO), CC BY 4.0", historie_ab="01/2001",
    verzoegerung="Eröffnung des ersten Handelstags nach dem Ausgabetag",
    schwaechen="Die Historie stammt aus von Hand geladenen Sammeldateien (PatentsView) und reicht bis zu deren Stand, "
               "danach das Amtsblatt; rund 0,4 % der Patente einer Ausgabe fehlen in PatentsView. Zuordnung über "
               "Firmennamen und eine von Hand geprüfte Liste von Patent-Töchtern mit Zeiträumen (Trefferquote im "
               "Prüfbericht), weitere Töchter mit eigenem Namen fehlen; ein Patent zählt bei der Firma, der der Inhaber "
               "am Ausgabetag gehörte, spätere Übertragungen bleiben unberücksichtigt; Zitationen stehen in GA1-09"))


# --------------------------------------------------------------------------- Ausgaben und Seiten
def wochennummer(tag: date) -> int:
    """Nummer der Ausgabe im Jahr: der wievielte Dienstag (der Ordner ``week45`` gehört zum 45. Dienstag)."""
    return (tag.timetuple().tm_yday - 1) // 7 + 1


def ausgabetage(heute: date, wochen: int = WOCHEN) -> list[date]:
    """Die letzten Dienstage bis ``heute``, jüngster zuerst."""
    letzter = heute - timedelta(days=(heute.weekday() - 1) % 7)
    return [letzter - timedelta(weeks=i) for i in range(wochen)]


def _text(s: str) -> str:
    return LEERRAUM.sub(" ", html.unescape(MARKE.sub("", s)).replace("\xa0", " ")).strip()


def _gleich(s: str) -> str:
    """Vergleichsform eines Namens: Großbuchstaben, ohne Satzzeichen und ohne den Artikel."""
    return " " + " ".join(w for w in OHNE_ZEICHEN.sub(" ", s.upper()).split() if w != "THE") + " "


def lies_seite(seite: str) -> tuple[date | None, list[tuple[str, str]], dict[str, str]]:
    """Eine Seite des Verzeichnisses: Ausgabetag, Verweise (Name, Patentnummer) und je Patentnummer der Text
    im Eintrag des ersten Erfinders vor der Nummer."""
    m = AUSGABETAG.search(_text(seite[:4000]))
    tag = None
    if m and m.group(2).lower() in MONATE:
        tag = date(int(m.group(3)), MONATE[m.group(2).lower()], int(m.group(1)))
    verweise: list[tuple[str, str]] = []
    erst: dict[str, str] = {}
    name = None
    for stufe, inhalt in EINTRAG.findall(seite):
        treffer = VERWEIS.search(inhalt)
        if stufe == "1":
            t = _text(inhalt)
            if t.endswith(SIEHE):
                name = t[:-len(SIEHE)].strip()
            else:
                name = None
                if treffer:
                    erst[treffer.group(1)] = _text(inhalt[:treffer.start()])
        elif name and treffer:
            verweise.append((name, treffer.group(1)))
    return tag, verweise, erst


def normiere(nummer: str) -> str:
    """Patentnummer ohne führende Nullen hinter dem Vorsatz (Amtsblatt „RE050717“, PatentsView „RE50717“)."""
    m = NUMMER.match(nummer)
    return m.group(1) + m.group(2) if m else nummer


def ist_organisation(name: str) -> bool:
    """Ein Verweisname ohne Komma oder mit einer Rechtsform hinter dem letzten Komma ist keine Person
    („Nachname, Vorname“). Zweibuchstabige Formen zählen nur groß geschrieben oder mit Punkt („Kim, Se“ ist ein Name)."""
    if "," not in name:
        return True
    rest = name.rsplit(",", 1)[1].strip()
    woerter = OHNE_ZEICHEN.sub(" ", rest.upper()).split()
    zusammen = "".join(woerter)
    if not woerter or not (all(w in FORMEN for w in woerter) or zusammen in FORMEN):
        return False
    return len(zusammen) > 2 or rest.isupper() or "." in rest


def nachpruefungen(nummern) -> set[str]:
    """Nummern einer Ausgabe, die weit unter der höchsten ihres Vorsatzes liegen: Nachprüfungsbescheide zu alten Patenten."""
    zerlegt = [(n, m.group(1), int(m.group(2))) for n in nummern if (m := NUMMER.match(n))]
    hoechste: dict[str, int] = {}
    for _, vorsatz, zahl in zerlegt:
        hoechste[vorsatz] = max(hoechste.get(vorsatz, 0), zahl)
    return {n for n, vorsatz, zahl in zerlegt
            if zahl < hoechste[vorsatz] - ABSTAND_NACHPRUEFUNG.get(vorsatz, ABSTAND_NACHPRUEFUNG_SONST)}


def werte_aus(verweise: list[tuple[str, str]], erst: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    """Inhaber je Patent aus den Verweisen aller Seiten einer Ausgabe. Vor „to“ stehen Miterfinder und Mitinhaber,
    dahinter der letzte Inhaber und der Titel."""
    alt = nachpruefungen(erst)
    teile = {}
    for n, t in erst.items():
        if n not in alt and ZU.search(t):
            teile[n] = _gleich(ZU.split(t, maxsplit=1)[1])
    paare = {(name, n) for name, n in verweise if n in teile and (_gleich(name) in teile[n] or ist_organisation(name))}
    t = pd.DataFrame(sorted(paare), columns=["inhaber", "nummer"])
    t["nummer"] = t["nummer"].map(normiere)
    vorsatz = t["nummer"].str.extract(r"^([A-Z]*)", expand=False)
    t["art"] = vorsatz.map(ARTEN).fillna("sonstige")
    info = {"patente": len(erst) - len(alt), "mit_inhaber": len(teile), "inhaber_erkannt": int(t["nummer"].nunique()),
            "erfindungspatente": sum(1 for n in erst if n.isdigit() and n not in alt), "nachpruefungen": len(alt)}
    return t[["nummer", "art", "inhaber"]], info


def _inhalt(antwort) -> str:
    return antwort.content.decode("utf-8", errors="replace")


def hole_ausgabe(abruf, tag: date) -> tuple[pd.DataFrame | None, dict]:
    """Liest die Ausgabe eines Dienstags; ``None``, wenn der Ordner (noch) eine andere Ausgabe enthält."""
    woche = wochennummer(tag)
    liste = abruf.hole(ADRESSE.format(woche=woche, seite=SEITENLISTE), erlaube_404=True)
    seiten = sorted(set(SEITENVERWEIS.findall(_inhalt(liste)))) if liste is not None else []
    seiten = seiten or SEITEN_ERSATZ
    verweise: list[tuple[str, str]] = []
    erst: dict[str, str] = {}
    for seite in seiten:
        antwort = abruf.hole(ADRESSE.format(woche=woche, seite=seite), erlaube_404=True)
        if antwort is None:
            if seite == seiten[0]:
                return None, {"grund": "nicht vorhanden"}
            continue
        seitentag, v, e = lies_seite(_inhalt(antwort))
        if seitentag != tag:
            return None, {"grund": f"Ordner week{woche:02d} enthält die Ausgabe vom {seitentag}"}
        verweise += v
        erst.update(e)
    tabelle, info = werte_aus(verweise, erst)
    info.update(woche=woche, seiten=len(seiten))
    if info["patente"] < MIN_PATENTE:
        return None, {"grund": f"nur {info['patente']} Patente gelesen (Aufbau geändert?)"}
    return tabelle.assign(tag=pd.Timestamp(tag))[SPALTEN_ERTEILT], info


# --------------------------------------------------------------------------- Historie aus PatentsView
def finde_datei(ordner: Path, stamm: str) -> Path | None:
    """Sammeldatei im Ordner, entpackt (``.tsv``) oder wie geladen (``.tsv.zip``)."""
    for endung in (".tsv", ".tsv.zip"):
        if (Path(ordner) / (stamm + endung)).exists():
            return Path(ordner) / (stamm + endung)
    return None


def oeffne(pfad: Path):
    """Dateiobjekt einer Sammeldatei; aus einem Zip-Archiv das eine enthaltene Mitglied."""
    if pfad.suffix == ".zip":
        archiv = zipfile.ZipFile(pfad)
        return archiv.open(archiv.namelist()[0])
    return open(pfad, "rb")


def leseoptionen(spalten: list[str], block: int = 64 << 20) -> dict:
    """Optionen für den CSV-Leser von Arrow: Tabulator, Zeichenketten in Anführungszeichen, nur die genannten Spalten
    und alle als Text. Die Dateien sind mehrere Gigabyte groß; Arrow hält nur die gewählten Spalten im Speicher."""
    return {"read_options": pacsv.ReadOptions(block_size=block),
            "parse_options": pacsv.ParseOptions(delimiter="\t", newlines_in_values=True),
            "convert_options": pacsv.ConvertOptions(include_columns=spalten, column_types={s: pa.string() for s in spalten},
                                                    strings_can_be_null=False)}


def lies_tsv(pfad: Path, spalten: list[str]) -> pa.Table:
    with oeffne(pfad) as datei:
        return pacsv.read_csv(datei, **leseoptionen(spalten))


def als_tage(spalte: pa.ChunkedArray) -> pa.Array:
    """Datumsspalte (Text JJJJ-MM-TT) als Zeitstempel; unlesbare Angaben werden leer. Über die wenigen
    verschiedenen Werte, weil die Spalte Millionen Zeilen hat."""
    kodiert = spalte.combine_chunks().dictionary_encode()
    werte = pd.to_datetime(pd.Series(kodiert.dictionary.to_pylist(), dtype="object"), errors="coerce", format="%Y-%m-%d")
    return pc.take(pa.array(werte.to_numpy(dtype="datetime64[ns]"), type=pa.timestamp("ns"), from_pandas=True), kodiert.indices)


def als_schluessel(nummern) -> np.ndarray:
    """Patentnummern als Zahl: Vorsatz (Buchstaben zur Basis 27) mal 10^10 plus Ziffernfolge ohne führende Nullen;
    -1 bei anderem Aufbau. So lassen sich Millionen Nummern ohne Zeichenketten vergleichen."""
    if isinstance(nummern, pa.ChunkedArray):
        nummern = nummern.combine_chunks()
    teile = pc.extract_regex(nummern, MUSTER_NUMMER)
    zahl = pc.struct_field(teile, "z").cast(pa.int64()).fill_null(-1).to_numpy(zero_copy_only=False)
    vorsatz = pc.struct_field(teile, "v").dictionary_encode()
    werte = np.array([sum((ord(c) - 64) * 27 ** i for i, c in enumerate(reversed(v))) for v in vorsatz.dictionary.to_pylist()] + [0],
                     dtype=np.int64)
    kode = werte[vorsatz.indices.fill_null(len(werte) - 1).to_numpy(zero_copy_only=False)]
    return np.where(zahl >= 0, kode * 10 ** 10 + zahl, -1)


def lies_patentsview(ordner: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Erteilte Patente mit ihren Inhabern aus den Sammeldateien von PatentsView: Tabelle wie ``patente_erteilt``,
    Kennzahlen je Ausgabetag wie ``patente_ausgaben`` und Angaben zu den Dateien. Zurückgezogene Patente und
    Inhaber ohne Organisation (Privatpersonen) bleiben weg.

    Die Dateien haben je rund neun Millionen Zeilen. Die Patentliste liegt deshalb nur als Zahlenfelder im Speicher
    (Nummer als Schlüssel, Tag, Art), die Inhaberdatei wird in Blöcken gelesen und über den Schlüssel zugeordnet."""
    pfad = finde_datei(ordner, DATEI_PATENT)
    if pfad is None:
        raise RuntimeError(f"{DATEI_PATENT}.tsv fehlt in {ordner}")
    for stamm, spalte in DATEIEN_INHABER:
        pfad_inhaber = finde_datei(ordner, stamm)
        if pfad_inhaber is not None:
            break
    else:
        raise RuntimeError(f"{DATEIEN_INHABER[0][0]}.tsv fehlt in {ordner}")
    p = lies_tsv(pfad, ["patent_id", "patent_type", "patent_date", "withdrawn"])
    schluessel = als_schluessel(p["patent_id"])
    tag = als_tage(p["patent_date"]).to_numpy(zero_copy_only=False)
    typ = p["patent_type"].combine_chunks().dictionary_encode()
    art_je_typ = np.array([ARTEN_PV.index(w) if w in ARTEN_PV else len(ARTEN_PV) - 1 for w in typ.dictionary.to_pylist()] + [0],
                          dtype=np.int8)
    art = art_je_typ[typ.indices.to_numpy(zero_copy_only=False)]
    zurueck = pc.equal(p["withdrawn"], "1").combine_chunks().to_numpy(zero_copy_only=False)
    del p, typ
    gut = (schluessel >= 0) & ~zurueck & ~np.isnat(tag)
    info = {"datei_inhaber": pfad_inhaber.name, "patente": int(gut.sum()), "zurueckgezogen": int(zurueck.sum()),
            "ohne_datum": int(np.isnat(tag).sum()), "andere_nummern": int((schluessel < 0).sum())}
    if not gut.any():
        raise RuntimeError(f"keine Patente in {pfad}")
    folge = np.argsort(schluessel[gut], kind="stable")
    schluessel, tag, art = schluessel[gut][folge], tag[gut][folge], art[gut][folge]
    del zurueck, gut, folge
    pa.default_memory_pool().release_unused()

    mit_inhaber, erkannt, teile = np.zeros(len(schluessel), dtype=bool), np.zeros(len(schluessel), dtype=bool), []
    with oeffne(pfad_inhaber) as datei:
        for stapel in pacsv.open_csv(datei, **leseoptionen(["patent_id", spalte])):
            gesucht = als_schluessel(stapel.column(0))
            stelle = np.minimum(np.searchsorted(schluessel, gesucht), len(schluessel) - 1)
            treffer = schluessel[stelle] == gesucht
            mit_inhaber[stelle[treffer]] = True
            name = pc.utf8_trim_whitespace(pc.replace_substring_regex(stapel.column(1), pattern=r"\s+", replacement=" "))
            behalten = treffer & pc.not_equal(name, "").to_numpy(zero_copy_only=False)
            erkannt[stelle[behalten]] = True
            maske = pa.array(behalten)
            teile.append(pa.table({
                "tag": pa.array(tag[stelle[behalten]]),
                "nummer": pc.replace_substring_regex(stapel.column(0).filter(maske), pattern=r"^([A-Z]*)0+([0-9])", replacement=r"\1\2"),
                "art": pa.DictionaryArray.from_arrays(pa.array(art[stelle[behalten]], type=pa.int8()), pa.array(ARTEN_PV)),
                "inhaber": name.filter(maske)}))
    tage = pd.DataFrame({"tag": tag, "patente": 1, "mit_inhaber": mit_inhaber, "inhaber_erkannt": erkannt,
                         "erfindungspatente": art == 0}).groupby("tag", as_index=False).sum()
    tage = tage.astype({s: "int64" for s in ("patente", "mit_inhaber", "inhaber_erkannt", "erfindungspatente")})
    tage = tage.assign(nachpruefungen=0, woche=[wochennummer(d.date()) for d in tage["tag"]], seiten=0,
                       herkunft=HERKUNFT_PATENTSVIEW, lesart=LESART)
    info.update(von=tage["tag"].min().date().isoformat(), bis=tage["tag"].max().date().isoformat())
    del schluessel, tag, art, mit_inhaber, erkannt
    # Zeichenketten bleiben in Arrow (ein Bruchteil des Speichers von Python-Zeichenketten), die Art als Kategorie
    erteilt = pa.concat_tables(teile).to_pandas(types_mapper=lambda typ: pd.ArrowDtype(typ) if pa.types.is_string(typ) else None)
    del teile
    pa.default_memory_pool().release_unused()
    return erteilt[SPALTEN_ERTEILT], tage, info


# --------------------------------------------------------------------------- Zuordnung und Parameter
def ordne_zu(inhaber: pd.DataFrame, firmen: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """CIK je Inhabername: Liste der Patent-Töchter mit ihren Zeiträumen, sonst Namensabgleich (exakt, früherer Name,
    Kernname). Ein Inhaber mit wechselnder Mutter hat eine Zeile je Zeitraum (``gilt_ab`` einschließlich, ``gilt_bis``
    ausschließlich; leer = unbegrenzt). Rückgabe: Zuordnung und die Mütter der Liste, die bei EDGAR nicht zu finden sind."""
    abgleich = Namensabgleich(firmen)
    bekannt = set(firmen["cik"].astype(int))
    unbekannt: set[str] = set()

    def selbst(name: str) -> tuple:
        cik, konfidenz, art = abgleich.finde(name, aehnlich=False)
        return (cik, konfidenz, art) if cik is not None and konfidenz >= MINDEST_KONFIDENZ else (None, 0.0, art if cik is None else "keiner")

    def mutter(m, name: str) -> tuple:
        if m is None:
            return selbst(name)
        cik = (m if m in bekannt else None) if isinstance(m, int) else abgleich.finde(m, aehnlich=False)[0]
        if cik is None:
            unbekannt.add(str(m))
            return None, 0.0, "keiner"
        return cik, 0.95, "tochter"

    zeilen = []
    for name, patente in zip(inhaber["inhaber"], inhaber["patente"]):
        stufen = STUFEN.get(bereinige(name))
        if stufen is None:
            zeilen.append((name, patente, *selbst(name), None, None))
            continue
        for ab, bis, m in stufen:
            zeilen.append((name, patente, *mutter(m, name), ab, bis))
    z = pd.DataFrame(zeilen, columns=["inhaber", "patente", "cik", "konfidenz", "art", "gilt_ab", "gilt_bis"])
    z["cik"] = z["cik"].astype("Int64")
    for spalte in ("gilt_ab", "gilt_bis"):
        z[spalte] = pd.to_datetime(z[spalte]).astype("datetime64[ns]")
    return z, sorted(unbekannt)


def baue_parameter(erteilt: pd.DataFrame, zuordnung: pd.DataFrame) -> pd.DataFrame:
    """Je Firma und Ausgabetag die Zahl der Erfindungspatente (ab ``PARAMETER_AB``)."""
    treffer = zuordnung[zuordnung["cik"].notna()][["inhaber", "cik", "gilt_ab", "gilt_bis"]]
    z = erteilt[(erteilt["art"] == "utility") & (erteilt["tag"] >= PARAMETER_AB)].merge(treffer, on="inhaber", how="inner")
    z = z[(z["gilt_ab"].isna() | (z["tag"] >= z["gilt_ab"])) & (z["gilt_bis"].isna() | (z["tag"] < z["gilt_bis"]))]
    if z.empty:
        return leer()
    z = z.drop_duplicates(["cik", "tag", "nummer"]).groupby(["cik", "tag"], as_index=False).size()
    return als_werte(z.rename(columns={"size": "wert"}), "GA1-01")


def als_werte(z: pd.DataFrame, parameter_id: str) -> pd.DataFrame:
    """Parameter-Tabelle aus Werten je Firma und Ausgabetag (Spalten cik, tag, wert): Ereignis ist der Ausgabetag,
    bekannt zur Eröffnung des nächsten Handelstags."""
    zeit = {}
    for tag in z["tag"].drop_duplicates():
        d = pd.Timestamp(tag).date()
        zeit[tag] = (pd.Timestamp(datetime.combine(d, time(0, 0), tzinfo=ET)).tz_convert("UTC"),
                     pd.Timestamp(handelbar_ab(datetime.combine(d, time(18, 0), tzinfo=ET))), d.isoformat())
    return als_parameter(pd.DataFrame({
        "cik": z["cik"].astype("int64").to_numpy(), "parameter_id": parameter_id,
        "ereignis_zeit": [zeit[t][0] for t in z["tag"]], "verfuegbar_ab": [zeit[t][1] for t in z["tag"]],
        "wert": z["wert"].to_numpy(dtype="float64"), "stand": [zeit[t][2] for t in z["tag"]]}))


# --------------------------------------------------------------------------- Lauf
def _pfad_jahr(ablage: Ablage, jahr: int) -> Path:
    return ablage.bereinigt / f"bereinigt__{TABELLE_ERTEILT}__{int(jahr)}.parquet"


def _lies_jahr(ablage: Ablage, jahr: int, spalten: list[str] | None = None) -> pd.DataFrame:
    pfad = _pfad_jahr(ablage, jahr)
    if not pfad.exists():
        return pd.DataFrame(columns=spalten or SPALTEN_ERTEILT)
    t = pd.read_parquet(pfad, columns=spalten)
    if "tag" in t.columns:
        t["tag"] = pd.to_datetime(t["tag"])
    return t


def _schreibe_jahre(ablage: Ablage, neu: pd.DataFrame, ersetzt_bis: pd.Timestamp | None = None) -> list[int]:
    """Fügt Zeilen in die Jahresdateien ein. Vorhandene Zeilen derselben Ausgabetage werden ersetzt, mit
    ``ersetzt_bis`` alle Zeilen bis zu diesem Tag (die Sammeldatei ersetzt das Amtsblatt, soweit sie reicht)."""
    jahre = []
    for jahr, teil in neu.groupby(neu["tag"].dt.year):
        bestand = _lies_jahr(ablage, int(jahr))
        if len(bestand):
            weg = bestand["tag"].isin(teil["tag"].unique())
            if ersetzt_bis is not None:
                weg |= bestand["tag"] <= ersetzt_bis
            if not weg.all():
                teil = pd.concat([bestand[~weg], teil], ignore_index=True)
        teil = teil[SPALTEN_ERTEILT].assign(art=teil["art"].astype("object")).drop_duplicates(["tag", "nummer", "inhaber"])
        teil = teil.sort_values(["tag", "nummer", "inhaber"], kind="stable").reset_index(drop=True)
        ablage.schreibe_bereinigt(TABELLE_ERTEILT, str(int(jahr)), teil)
        jahre.append(int(jahr))
    return jahre


def lauf(ablage: Ablage, arbeits: Path | None = None, modus: str = "laufend", abruf=None,
         budget: Zeitbudget | None = None, heute: date | None = None, max_fehler: int = 3,
         historie: Path | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    hinweise: list[str] = []
    if not list(ablage.bereinigt.glob("bereinigt__edgar_firmen__*.parquet")):
        raise RuntimeError("Firmentabelle fehlt (Quelle edgar_index zuerst ausführen)")
    heute = heute or datetime.now(ET).date()
    budget = budget or Zeitbudget()
    ausgaben = ablage.lies_bereinigt(TABELLE_AUSGABEN)
    if len(ausgaben):
        ausgaben["tag"] = pd.to_datetime(ausgaben["tag"])
        for spalte, vorgabe in (("nachpruefungen", 0), ("herkunft", HERKUNFT_AMTSBLATT), ("lesart", 1)):
            if spalte not in ausgaben.columns:                 # Bestand aus der ersten Fassung des Leseverfahrens
                ausgaben[spalte] = vorgabe

    # Historie aus den Sammeldateien: ersetzt alle Ausgabetage bis zum Stand der Dateien
    info_historie = None
    if historie is not None:
        erteilt_h, tage_h, info_historie = lies_patentsview(Path(historie))
        bis = tage_h["tag"].max()
        _schreibe_jahre(ablage, erteilt_h, ersetzt_bis=bis)
        del erteilt_h
        pa.default_memory_pool().release_unused()
        ausgaben = pd.concat([tage_h, ausgaben[ausgaben["tag"] > bis]], ignore_index=True) if len(ausgaben) else tage_h
        print(f"Patente: Historie {info_historie['von']} bis {info_historie['bis']} aus {info_historie['datei_inhaber']} "
              f"({info_historie['patente']} Patente)", flush=True)

    # laufende Ausgaben des Amtsblatts; Ausgaben einer älteren Lesart werden neu gelesen, solange sie vorliegen
    bekannt = set(ausgaben.loc[ausgaben["lesart"] >= LESART, "tag"].dt.date) if len(ausgaben) else set()
    stand_historie = ausgaben.loc[ausgaben["herkunft"] == HERKUNFT_PATENTSVIEW, "tag"].max() if len(ausgaben) else pd.NaT
    neu, neue_zeilen, fehlend, fehler, abgebrochen = [], [], [], 0, False
    for tag in ausgabetage(heute):                             # jüngste zuerst
        if tag in bekannt or (pd.notna(stand_historie) and tag <= stand_historie.date()):
            continue
        if budget.abgelaufen():
            abgebrochen = True
            break
        abruf = abruf or Abruf(anfragen_pro_sekunde=2, kontakt_noetig=False)
        try:
            tabelle, info = hole_ausgabe(abruf, tag)
        except QuelleNichtErreichbar as stoerung:
            fehler += 1
            hinweise.append(f"Ausgabe {tag} nicht gelesen ({str(stoerung)[:100]})")
            if fehler >= max_fehler:
                abgebrochen = True
                break
            continue
        if tabelle is None:
            fehlend.append((tag, info["grund"]))
            continue
        neue_zeilen.append(tabelle)
        neu.append({"tag": pd.Timestamp(tag), **info, "herkunft": HERKUNFT_AMTSBLATT, "lesart": LESART})
        print(f"Patente: Ausgabe {tag} gelesen ({info['patente']} Patente)", flush=True)
    if neu:
        zusatz = pd.DataFrame(neu)
        ausgaben = pd.concat([ausgaben[~ausgaben["tag"].isin(zusatz["tag"])], zusatz], ignore_index=True) if len(ausgaben) else zusatz
        _schreibe_jahre(ablage, pd.concat(neue_zeilen, ignore_index=True))
    jahre = sorted(int(p.stem.rsplit("__", 1)[1]) for p in ablage.bereinigt.glob(f"bereinigt__{TABELLE_ERTEILT}__*.parquet"))
    if ausgaben.empty or not jahre:
        raise RuntimeError("keine Ausgabe des Amtsblatts gelesen: " + "; ".join([f"{t} ({g})" for t, g in fehlend[:3]] + hinweise[:3]))
    ausgaben = ausgaben.sort_values("tag").reset_index(drop=True)
    for spalte in ("patente", "mit_inhaber", "inhaber_erkannt", "erfindungspatente", "nachpruefungen", "woche", "seiten", "lesart"):
        ausgaben[spalte] = ausgaben[spalte].fillna(0).astype("int64")
    ablage.schreibe_bereinigt(TABELLE_AUSGABEN, "alle", ausgaben)

    # Zuordnung über alle Jahre, Parameter jahresweise (die Historie passt nicht auf einmal in den Speicher eines Laufs)
    firmen = ablage.lies_bereinigt("edgar_firmen")
    firmen = firmen[firmen["sic"].notna() | firmen["tickers"].notna()]     # nur Unternehmen, keine Privatpersonen
    zaehler = [_lies_jahr(ablage, jahr, ["nummer", "inhaber"]).groupby("inhaber", as_index=False).agg(patente=("nummer", "nunique"))
               for jahr in jahre]
    je_inhaber = pd.concat(zaehler, ignore_index=True).groupby("inhaber", as_index=False)["patente"].sum()
    zuordnung, unbekannt = ordne_zu(je_inhaber, firmen)
    ablage.schreibe_bereinigt(TABELLE_ZUORDNUNG, "alle", zuordnung)
    teile = [baue_parameter(_lies_jahr(ablage, jahr), zuordnung) for jahr in jahre if jahr >= PARAMETER_AB.year]
    teile = [t for t in teile if len(t)]
    parameter = als_parameter(pd.concat(teile, ignore_index=True)) if teile else leer()
    ablage.schreibe_parameter("uspto_patente", parameter)

    if abgebrochen and modus == "rueckwaerts":
        merke_fortsetzung(ablage.wurzel, "uspto_patente")
    juengste = ausgaben["tag"].max().date()
    offen = [t for t in ausgabetage(heute) if t not in set(ausgaben["tag"].dt.date)]
    # die Ausgabe eines Dienstags erscheint im Lauf des Tages; ältere fehlende Ausgaben sind ein Befund
    spaet = [f"{t} ({g})" for t, g in fehlend if (heute - t).days >= 2]
    if spaet:
        hinweise.append("nicht gelesen: " + "; ".join(spaet[:5]) + (" …" if len(spaet) > 5 else ""))
    if unbekannt:
        hinweise.append("Mütter der Töchterliste ohne eindeutigen Treffer bei EDGAR: " + ", ".join(unbekannt))
    heutig = zuordnung[zuordnung["gilt_bis"].isna()].reset_index(drop=True)       # eine Zeile je Inhaber
    quote = trefferquote(heutig, gewicht=heutig["patente"].astype("float64"))
    mit_kuerzel = heutig["cik"].isin(set(firmen.loc[firmen["tickers"].notna(), "cik"].astype(int)))
    anteil_boerse = float(heutig.loc[mit_kuerzel, "patente"].sum() / max(heutig["patente"].sum(), 1))
    hinweise.append(f"Zuordnung: {quote.get('quote', 0):.1%} der Inhabernamen, {quote.get('quote_gewichtet', 0):.1%} der "
                    f"Patente; {anteil_boerse:.1%} der Patente bei Firmen mit Börsenkürzel")
    amtsblatt = ausgaben[ausgaben["herkunft"] == HERKUNFT_AMTSBLATT]
    info = {"ausgaben_gelesen": int(len(ausgaben)), "ausgaben_amtsblatt": int(len(amtsblatt)),
            "ausgaben_neu": [z["tag"].date().isoformat() for z in neu],
            "ausgaben_offen": len(offen), "ausgaben_alte_lesart": int((amtsblatt["lesart"] < LESART).sum()),
            "juengste_ausgabe": juengste.isoformat(), "tage_seit_ausgabe": (heute - juengste).days,
            "patente": int(ausgaben["patente"].sum()), "erfindungspatente": int(ausgaben["erfindungspatente"].sum()),
            "inhaber": int(len(heutig)), "firmen": int(parameter["cik"].nunique()) if len(parameter) else 0,
            "anteil_boerse": round(anteil_boerse, 4), "trefferquote": quote}
    if info_historie is not None:
        info["historie"] = info_historie
    return parameter, info, hinweise
