# Fahrzeugtypen statt Marken

## Eigene Abstimmung speichern

Unter „Preset laden“ einen Namen eingeben und „Als eigenes Preset speichern“ drücken. Im Editor liegen neue JSON-Dateien sichtbar unter `addons/bungee/presets/custom`. Im exportierten Spiel liegen die mitgelieferten Presets offen unter `vehicle_presets` neben der EXE und eigene Presets unter `vehicle_presets/custom`. Das Preset erscheint direkt unter „Eigene Presets“; gleiche Namen erzeugen getrennte Dateien und mitgelieferte Presets werden nicht überschrieben.

Eigene Presets enthalten Fahrzeugwerte, Fahrhilfen, fahrzeugbezogene Klangregler und Soundbank-/Datei-Indizes. UI-Design, Dyno-Skala, laufende RPM, Motor-An/Aus, Umgebungs-Reverb und Innenraumperspektive werden nicht gespeichert. Anders als die mitgelieferten Fahrzeugtypen stellen eigene Presets beim Laden ausdrücklich auch deine fahrzeugbezogenen Klangregler wieder her. WAV-Dateien werden nicht kopiert; die Soundbank muss weiter vorhanden sein.

22 frei gestaltete Arcade-Presets, keine Nachbildungen konkreter Serienfahrzeuge.

- Alltag: 3-Zylinder-Kleinwagen, 4-Zylinder-Kompaktwagen, moderner 3-Zylinder-Turbo.
- Coupe / Sport: leichter 4-Zylinder-Sauger, Reihen-6-Turbo, V12-Gran-Turismo.
- V8 / Muscle: klassischer Sauger, klassischer Kompressor, modernes Sport-Muscle.
- Motorrad: Einzylinder, Zweizylinder-Roadster, Vierzylinder-Supersport, V2-Cruiser.
- Motorsport: Turbo-Tourenwagen, V8-GT, V10-Formelwagen.

Ergänzungen: 50er-Moped (4 PS), Stadtroller (6 PS), 125er-Einzylinder (15 PS), kleiner Oldtimer (48 PS), Lieferwagen (100 PS), Sportkombi (190 PS + 90 PS Turbo). Die kleinen Zweiräder haben feste Arcade-Vmax-Werte von 45, 60 und 110 km/h. Der Roller nutzt eine vereinfachte Ein-Gang-Automatik, keine echte CVT/Variomatik. Moped und Roller müssen im Funktionstest nicht 100 km/h erreichen.

## Abstimmung

Klassische Muscle-Setups haben keine TC und keine Launch Control. Moderne Sporttypen erhalten diese Hilfen; einfache und klassische Motorräder nicht. Der perfekte Rennstart bleibt für alle verfügbar, auch ohne Launch Control. Handschalter/Automatik/Sequenziell beschreiben den Schaltablauf; die Wahl zwischen automatischer und manueller Gangbedienung bleibt beim Spieler. Schwierigkeit bleibt ebenfalls eine Spielereinstellung.

Leistung ist Motor-Basisleistung **plus** separat eingetragene Turbo-/Kompressorleistung, sofern aktiviert. Motorradmasse ist als fahrfertige Gesamtmasse einschließlich Fahrer angenähert. Vmax wird außer beim Formelwagen über das vorhandene Arcade-Modell ermittelt.

Freies Hochdrehen, RPM-Abfall, Schaltzeit, Einkuppeln, Wobble, Motorglätte, Struggle, Wheelspin und Bremsen sind pro Typ abgestimmt. Alle verwenden Audio-Follow-Stärke 20, einen aktivierten künstlichen RPM-Begrenzer mit 50 RPM Rücksprung und unterschiedliche ACC/DCC-Übergangszeiten. Backfire, Getriebe-Whine, Turbo/BOV und Kompressorsound werden ausdrücklich gesetzt, damit keine alten Zusatzsounds vom vorherigen Typ hängen bleiben.

## Was unverändert bleibt

Soundbank und Datei-Indizes, Motor-Pitch, Resonanz, Höhen, Bus-Pegel und Phaserschutz bleiben deine Einstellungen. Zylinderzahl ist eine Beschreibung des gewünschten Typs, kein eigener Verbrennungs- oder Zündfolgensimulator: Wähle eine passende Motoraufnahme dazu. Die Frequenz und Stärke des Phaserschutzes bleiben unabhängig vom Fahrzeug-Preset.

Die bisherigen sieben JSON-Dateien sind vollständig gesichert unter `addons/bungee/backups/2026-08-30_202243_named_vehicle_presets/vehicles`. Sie wurden nur aus der aktiven Auswahl entfernt.
