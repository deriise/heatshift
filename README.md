# HeatShift

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/deriise/heatshift/actions/workflows/validate.yml/badge.svg)](https://github.com/deriise/heatshift/actions/workflows/validate.yml)

Home Assistant integration that shifts your heat pump to the cheapest hours of your dynamic energy contract, without losing comfort.

*Nederlandse uitleg: zie [hieronder](#nederlands).*

> ⚠️ **Work in progress.** HeatShift is still being tested and is not ready for use in your own installation. Settings and behaviour can change without notice.
>
> ⚠️ **In ontwikkeling.** HeatShift wordt nog getest en is niet geschikt voor gebruik in je eigen installatie. Instellingen en gedrag kunnen zonder aankondiging veranderen.

> **Disclaimer.** Use of HeatShift is voluntary and at your own risk. HeatShift is provided "as is", without any warranty, under the [Apache License 2.0](LICENSE). The makers and the installer are not liable for damage, higher energy costs or loss of comfort. Steering stays off until you turn it on.

## What it does

- **Heating:** every quarter HeatShift compares the current price with today's price range and shifts the heating in one of two ways:
  - **Offset:** in the most expensive part of the day it lowers the leaving water offset (default -2 °C). Optionally it raises it in the cheapest part.
  - **Room thermostat:** it shifts the room setpoint from a base temperature (default -1 °C when expensive, +0.5 °C when cheap), always between a lower and upper limit.
- **Hot water:** every night it finds the cheapest block (default 1 hour between 10:00 and 16:00) and heats the tank in that block if it is below a threshold.
- **Morning check:** at a set time (default 05:00) it heats the tank if it is too cold for the morning showers, then sets everything back.
- **Safety:** fixed limits on the offset, a minimum tank temperature below which it always heats, and when steering is off, stopped or without prices the offset goes back to 0.

## Supported

| Part | Version 0.1 | Later |
| --- | --- | --- |
| Heating | Any climate entity: a leaving water offset (Daikin Altherma via Onecta) or a room thermostat (Madoka, Tado, Netatmo, Zigbee) | |
| Hot water | Daikin Altherma via Onecta (water heater with `performance` mode) | Other brands |
| Prices | Frank Energie, and sensors with a `start`/`end`/`value` price list | Tibber, EnergyZero, Zonneplan, Nord Pool tested |

## Installation

1. In HACS, open the menu, choose **Custom repositories**, add `https://github.com/deriise/heatshift` as type **Integration**.
2. Install **HeatShift** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration > HeatShift**.
4. Pick the price sensor, the control method (offset or room thermostat) and its climate entity, and optionally the water heater and tank sensor. Accept the disclaimer.
5. Check the settings, then turn on the **Steering** switch.

If you already steer the heat pump with automations, turn those off before you turn HeatShift on, so they do not overrule each other.

## Entities

| Entity (NL name) | Meaning |
| --- | --- |
| Steering (Sturing) | Main switch. Off: the heat pump runs on its own settings. |
| Status | Off, active, no prices or heating off |
| Planned offset or Planned setpoint (Geplande offset / Gepland setpoint) | Value for this quarter. Attribute `plan` holds today's plan. |
| Hot water start (Start warm water) | Start of today's cheapest hot water block |

---

## Nederlands

HeatShift laat je warmtepomp draaien op de goedkoopste uren van je dynamische energiecontract, zonder comfortverlies.

> **Disclaimer.** Gebruik van HeatShift is vrijwillig en op eigen risico. HeatShift wordt geleverd zoals het is, zonder garantie, onder de [Apache License 2.0](LICENSE). De makers en de installateur zijn niet aansprakelijk voor schade, hogere energiekosten of comfortverlies. De sturing staat uit tot je hem zelf aanzet.

### Wat het doet

- **Verwarming:** elk kwartier vergelijkt HeatShift de huidige prijs met het prijsbereik van vandaag en verschuift de verwarming op een van twee manieren:
  - **Offset:** in het duurste deel van de dag gaat de offset van de aanvoertemperatuur omlaag (standaard -2 °C). Optioneel gaat hij omhoog in het goedkoopste deel.
  - **Kamerthermostaat:** het kamersetpoint verschuift vanaf een basistemperatuur (standaard -1 °C bij dure en +0,5 °C bij goedkope prijs), altijd tussen een onder- en bovengrens.
- **Warm water:** elke nacht zoekt HeatShift het goedkoopste blok (standaard 1 uur tussen 10:00 en 16:00) en warmt de boiler dan op als die onder een drempel zit.
- **Ochtendcheck:** op een vast tijdstip (standaard 05:00) warmt HeatShift de boiler op als die te koud is voor het douchen, en zet daarna alles terug.
- **Veiligheid:** vaste grenzen voor de offset, een minimale boilertemperatuur waaronder altijd wordt opgewarmd, en bij uitzetten, stoppen of zonder prijzen gaat de offset terug naar 0.

### Installeren

1. Open in HACS het menu, kies **Custom repositories** en voeg `https://github.com/deriise/heatshift` toe als **Integration**.
2. Installeer **HeatShift** en herstart Home Assistant.
3. Ga naar **Instellingen > Apparaten en diensten > Integratie toevoegen > HeatShift**.
4. Kies de prijssensor, de manier van sturen (offset of kamerthermostaat) met de bijbehorende climate-entiteit, en eventueel de boiler en de temperatuursensor. Ga akkoord met de disclaimer.
5. Controleer de instellingen en zet daarna **Sturing** aan.

Stuur je de warmtepomp al met eigen automatiseringen? Zet die uit voordat je HeatShift aanzet, anders overschrijven ze elkaar.

## License

[Apache License 2.0](LICENSE)
