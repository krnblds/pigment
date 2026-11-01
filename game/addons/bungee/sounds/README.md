# Motoraufnahmen und Effekte

## Deutsch

- `Vehicles/<Fahrzeug>/`: ACC, DCC, Idle und Limiter-WAV desselben Motors bleiben zusammen.
- `Effects/Whine/`: Getriebe-Whine.
- `Effects/ShiftUp/`, `Effects/ShiftDown/`: einzelne Gangwechsel-Sounds.
- `Effects/skid/`: Reifenquietschen.
- `Effects/Turbo/`, `Effects/BOV/`, `Effects/Supercharger/`: Aufladung und Blow-off.
- `Effects/Backfire/`: Pops und Bangs.
- `Effects/EngineState/`: Starter und Kill-Sound.

Im Engine-Inspector waehlt `Soundbank Path` den Vehicles-Ordner und `Effects Path` den Effects-Ordner. Fahrzeugnamen, Dateinamen und Indexreihenfolge sind unveraendert. Alte eigene Presets mit `res://addons/bungee/sounds` als Soundbank-Pfad werden beim Laden automatisch auf `Vehicles` umgeleitet. Eigene Presets speichern ab jetzt beide Pfade. WAVs und ihre Importparameter wurden nicht klanglich veraendert.

Die im Starter-Paket enthaltenen `.wav.import`-Dateien sind absichtlich Teil des Addons: Sie importieren Motor-Loops und kontinuierliche Effekte automatisch als PCM mit Loop. Backfire, BOV und Gangwechsel bleiben PCM-One-Shots. Die erzeugten Dateien unter `.godot/imported` gehören nicht ins Addon und werden auf jedem Rechner neu erstellt.

Der Stand vor dem Umzug liegt unter `addons/bungee/backups/2026-08-31_before_audio_folder_split`; `.gdignore` verhindert den Import dieser Sicherung als zweites Asset-Set.

## English

- `Vehicles/<Vehicle>/`: ACC, DCC, idle, and limiter WAVs for one engine stay together.
- `Effects/Whine/`: transmission whine.
- `Effects/ShiftUp/`, `Effects/ShiftDown/`: individual shift sounds.
- `Effects/skid/`: tire squeal.
- `Effects/Turbo/`, `Effects/BOV/`, `Effects/Supercharger/`: forced-induction sounds.
- `Effects/Backfire/`: individual pops and bangs.
- `Effects/EngineState/`: starter and engine-kill sounds.

`Soundbank Path` selects the Vehicles directory and `Effects Path` selects the shared Effects directory. Use uncompressed PCM WAV files with reasonably matched loudness. Vehicle presets reference files but do not copy them. Only distribute recordings for which you have the necessary rights.

The `.wav.import` files included in the starter package are intentional. They automatically import engine loops and continuous effects as looped PCM, while backfire, BOV, and shift sounds remain PCM one-shots. Generated files under `.godot/imported` are not shipped and are recreated on each computer.
