# Einstellungen finden

Die Inspector-Kategorien sind nummeriert. Eigenschaftsnamen, Werte und Preset-Schlüssel bleiben unverändert: Bestehende Szenen und Presets verwenden dieselben Einstellungen. Ein geladenes Preset kann Fahrzeugwerte weiterhin überschreiben.

## Welchen Node auswählen?

| Script | Zuständigkeit |
| --- | --- |
| `bungee_engine_audio.gd` | Soundbank, Audio-RPM-Verfolgung, ACC/DCC-Mix, WAVs, Filter, gemeinsamer Audiomix |
| `bungee_vehicle_simulator.gd` | Leistung, Masse, Fahrzeug-RPM, Getriebe, Start, Traktion, Fahrhilfen; außerdem UI-Konfiguration |
| `bungee_simulator_ui.gd` | Darstellung und Bedienung. Keine eigenen exportierten Fahrzeugwerte; liest und bedient die beiden Nodes oben |

## Häufig gesuchte Einstellungen

| Gesucht | Inspector-Pfad |
| --- | --- |
| Phaser-Geräusch bei stehender/langsam steigender Audio-RPM | Engine → **01 Motorwiedergabe → Stehende Audio-RPM - Phaserschutz** |
| Wie schnell der Sound der RPM folgt | Engine → 01 Motorwiedergabe → RPM-Verfolgung und Grund-Pitch → `distance_strength` |
| Weicher/harter Wechsel zwischen ACC und DCC | Engine → 01 Motorwiedergabe → ACC-DCC - Ueberblendung |
| RPM-Begrenzer an/aus und Rücksprungweite | Simulator → **01 Fahrzeug und Motor → RPM-Begrenzer - Ruecksprung** |
| DCC beim Limiter-Cut / schneller Audio-Rücksprung | Engine → 02 Motorzustand und Loops → RPM-Begrenzer - Klang beim Ruecksprung |
| Echte Limiter-WAV | Engine → 02 Motorzustand und Loops → Drehzahlende - Limiter-WAV |
| Audio vor Clipping schützen, ohne RPM-Eingriff | Engine → **03 Klang und Audioausgabe → Audio Hard-Limiter - Clipping-Schutz, keine RPM** |
| Tunnel, Garage, Draußen oder Unterführung einblenden | Engine → **03 Klang und Audioausgabe → Umgebungs-Reverb - Tunnel und Raeume** |
| Straßenauto-, Rennauto- oder blecherner Cockpit-Klang | Engine → **03 Klang und Audioausgabe → Innenraumklang - Fahrerperspektive** |
| Idle ohne WAV simulieren | Simulator → 01 Fahrzeug und Motor → Leerlauf - Simulation ohne Idle-WAV |
| Idle-WAV und ihr Übergang | Engine → 02 Motorzustand und Loops → Leerlauf - Idle-WAV |
| Last-/Schub-Struggle, Nm-Kurve | Simulator → 01 Fahrzeug und Motor → Struggle - Last und Schubbetrieb |
| Gas-/Schaltwobble nur als Pitch | Simulator → 04 Aufladung und Klangimpulse → Gas- und Schaltwobble - Nur Pitch |
| Freies Hochdrehen / freier RPM-Abfall | Simulator → 02 Getriebe und Fahrverhalten → Freies Hochdrehen - Handbremse |
| Abfallhilfe nur im Startfenster | Simulator → 03 Rennstart und Fahrhilfen → Schwierigkeit - Start und Schalten |
| TC, perfekter Start, Launch Control | Simulator → 03 Rennstart und Fahrhilfen |
| Turbo-/Supercharger-Leistung | Simulator → 04 Aufladung und Klangimpulse |
| Turbo-/Supercharger-Sound, BOV | Engine → 05 Aufladung |
| Backfire: Sound / Bedingungen / Impulse | Engine → 06 Backfire, in drei getrennten Gruppen |
| Dyno-Skala, Debug, Sprache, Design | Simulator → 05 System und Anzeige |

## Linkes Laufzeitmenü

Beim Phaserschutz bleiben Mindestbewegung, Frequenz und Stärke unabhängig: Frequenz (0,1–20 Hz) steuert das Tempo der Pitchbewegung; Stärke (0–0,15) ihren Ausschlag. Stärke 0 schaltet nur die Pitchbewegung aus, nicht die Mindestbewegung. Im Inspector heißt die Stärke aus Kompatibilitätsgründen weiterhin `stationary_pitch_motion`, unter „Pitchbewegung - Frequenz und Staerke“. Bisheriges Verhalten: 2 Hz und Stärke 0,04.

Die Farbreihenfolge bleibt: Fahrzeug → Sound → Extras → Anzeige. Phaserschutz hat innerhalb der ACC/DCC-Wiedergabe eine eigene aufklappbare Gruppe. Künstliches Idle steht bei Fahrzeug, WAV-Loops bei Sound. Der Rücksprung-Klang des RPM-Begrenzers ist getrennt vom physikalischen Rücksprung. Headroom steht beim Audio-Pegel/Clipping-Schutz; reiner Pitch-Wobble bei Sound.

Umgebungs-Reverb und Innenraumklang lassen sich im Laufzeitmenü jeweils von 0 bis 1 einblenden. Beide beschreiben Strecke beziehungsweise Fahrerperspektive und werden deshalb nicht in Fahrzeug-Presets gespeichert oder daraus geladen.

## Skripteditor

### Versuch: getrennte Fahrphysik und Audio-RPM

Seit dem Backup `2026-08-31_204253_before_physics_audio_separation` gibt es eine eigene `physics_rpm`: Leistung, Turbo-/Kompressordruck, Startbewertung und automatische Gangwahl folgen dieser Drehzahl. `rpm_normalized` bleibt das Audio-Ziel mit Struggle und hörbaren Limiter-Cuts; Follow Strength steuert den Audiocursor, nicht mehr den Vortrieb. Die Debug-Anzeige zeigt Physik- und Audio-RPM getrennt.

Nachkorrektur: Die Dyno-Zahlen (RPM, PS/Nm) verwenden bei aktivem Simulator `physics_rpm`. Zwei senkrechte Linien zeigen die Drehzahlen getrennt: Physik-RPM durchgezogen in der Start-/Schaltzonenfarbe, Audio-RPM gestrichelt in der Textfarbe mit Kurvenpunkten. Eine Legende neben DYNO kennzeichnet beide. Die Linien sind rein grafisch, ohne Rückwirkung auf Leistung, Startbewertung oder Schaltampel. Im manuellen Audiotest bleibt der Cursor sichtbar. Struggle liest die physikalische Nm-Kurve statt seinen eigenen Audio-Ausschlag zurück. Während aktivem Struggle sowie Limiter-Push/Cut gilt für ACC/DCC die erprobte feste Follow-Referenz 20; außerhalb dieser Effekte bleibt der Follow-Regler wirksam. Cut-Stärke und Wheelspin-Push-Rampe bleiben separat erhalten. Damit verändert der allgemeine Follow-Regler nicht zusätzlich deren Audio-Reaktionsrate.

Regression: `tools/test_real_follow_independence.gd` rendert echte Bungee-Samples mit identischen zeitgesteuerten Eingaben bei Follow 20/100 und prüft Fahrwerte, Boost, Dyno und vollständige Limiter-Zyklen. Das ist kein subjektiver Hörtest und kein FPS-/Soundkarten-Test.

Follow-Stabilität: Die frühere Rechnung `Dist * Stärke` erzeugte bei Stärke 100 sogar ohne Simulator ein dauerhaftes Pendeln um ein festes Ziel (im Test ca. 0,35–0,64 bei Ziel 0,50). Die Audio-Geschwindigkeit nutzt jetzt eine exponentielle Annäherung mit zeit- und pitchabhängiger Grain-Reserve. Hohe Werte reagieren schneller, nähern sich aber einer stabilen Reaktionsgrenze. Das ist keine Änderung an Fahrzeugleistung oder Struggle-Einstellungen. `tools/test_follow_settle.gd` prüft Follow 5/20/100 bei 30/60/120 Hz und Pitch 0,5/1/2 mit echtem Bungee-Rendering.

Die optionale `Zielbremsung` reduziert die Audio-Follow-Reaktion nur innerhalb des eingestellten Restabstands. Standard: Bereich 0,08 und Stärke 0,90; direkt am Ziel bleiben damit 10 % der stabilen Follow-Reaktion übrig. Außerhalb des Bereichs gilt die volle Follow-Stärke. ACC und DCC verwenden dieselbe Kurve. Limiter-Cut/Push und Struggle sind ausgenommen, weil sie bereits eine feste eigene Reaktionsrate besitzen. Bereich oder Stärke 0 deaktiviert die Zielbremsung.

Freies Hochdrehen wirkt bei gehaltener Handbremse weiterhin auf die reale Startdrehzahl. Es kann deshalb den Rennstart beeinflussen, soll aber während der normalen Fahrt keine Zusatzleistung erzeugen. Turbo-Aufbau richtet sich jetzt nach Druckdifferenz statt Audio-Dist (alter Property-Name bleibt für Presets erhalten). Automatische Schaltpunkte hängen nicht mehr vom Beginn einer Limiter-WAV ab. Bestehende Presets können sich dadurch anders fahren; die alte Abstimmung ist gesichert.

Die `Start-Abfall Schwierigkeit` wirkt ausschließlich beim Gaswegnehmen in der blauen/guten und grünen/perfekten Rennstartzone. 0 bedeutet maximale Hilfe, 1 unveränderten freien RPM-Abfall. Die Zwischenwerte nutzen eine progressive Kurve, damit z.B. 0,65 gegenüber 1 deutlich wahrnehmbar ist. Physik-RPM und Audio-Ziel verwenden denselben Faktor.

Die frühere `RPM-/Schalt-Reaktionshilfe` wurde entfernt. Sie drosselte im manuellen Modus kurz vor dem perfekten Schaltpunkt künstlich den Vortrieb, war kaum wahrnehmbar und überschnitt sich konzeptionell mit der Timing-Fenster-Schwierigkeit. Übrig bleiben die sichtbaren Gut-/Perfekt-Fenster und die separate Start-Abfallhilfe; außerhalb des Start-Abfalls wird keine Fahrzeugleistung als Timing-Hilfe verändert.

`Anfahr-RPM Aufbau` und `Einkuppeln / Settle` werden nicht mehr im Laufzeitmenü angeboten. Ihre internen Werte bleiben Bestandteil der Fahrzeug-Presets, damit Kleinwagen weich und Rennfahrzeuge weiterhin kurz einkuppeln. Eigene Presets speichern diese Abstimmung ebenfalls; im normalen Testmenü ist keine Handarbeit dafür nötig.

Die Funktionsbereiche haben benannte `#region`-Abschnitte zum Einklappen. Rechenlogik und Aufrufreihenfolge wurden bei dieser Sortierung nicht geändert. `tools/` enthält Tests; `backups/` enthält historische Versionen und wurde nicht umsortiert.
