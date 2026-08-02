# CardBridge Microphone driver

This directory contains a CardBridge-specific derivative of
[BlackHole](https://github.com/ExistentialAudio/BlackHole). The audio engine is
licensed under GNU GPLv3; see `LICENSE-GPL-3.0.txt`. BlackHole is copyright
Existential Audio Inc. The modified build is not affiliated with, endorsed by,
or distributed under the BlackHole name or branding.

Upstream base: BlackHole `v0.7.1`, commit
`e2b22aaaba4e507a097131704bf96dabc004d9cf`.

CardBridge-specific changes:

- unique bundle ID, factory UUID, device UIDs, names, and manufacturer;
- a public input-only microphone and a separate output-only feed device;
- 16 kHz and 48 kHz speech-oriented sample rates;
- an experimental USB Core Audio transport declaration.

The USB declaration only changes the HAL property returned to applications. It
does not create USB hardware or an IOKit USB device.
