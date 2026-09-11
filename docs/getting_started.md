# Getting Started

A guide for your first hour with a working SeedSigner. It assumes the device is
already built and booted — see the [README](../README.md) for hardware and software
installation.

> This document is part of an unofficial fork. See the warning at the top of the
> [README](../README.md).

## Trying it before you build one

You do not need the hardware to see what any of this looks like. From a clone of this
fork, `python tools/emulator.py` opens the device in a window on your computer — arrow
keys for the joystick, Enter to select. Every menu, every warning and every flow in this
guide is there, apart from anything that needs the camera. The
[README](../README.md#running-it-without-hardware) has the details.

## What SeedSigner is

SeedSigner is a *stateless* signing device. It holds your seed in memory only while
it has power. It has no WiFi, no Bluetooth, and no persistent storage for secrets.
Data goes in by scanning QR codes with the camera and comes out as QR codes on the
screen. Nothing else.

The practical consequence, and the thing that surprises most newcomers:

**When you unplug it, your seed is gone from the device.** That is by design, not a
malfunction. Every time you want to sign a transaction you load your seed again. Your
seed lives on your paper or metal backup, never on the device.

## The first screen

On every power-on the device offers a **quick guide** — three screens covering the
controls, the fact that it does not keep your seed, and where to start. *Continue* skips
straight to the main menu.

It is offered once per boot rather than once ever, because nothing about a boot is
written to disk. You can reopen it any time under **Settings > Quick guide**.

## Controls

The device has a five-way joystick and three buttons along the side.

| Input | What it does |
|---|---|
| Joystick up / down | Move between menu entries |
| Joystick press | Select the highlighted entry |
| Joystick left | Jump straight to the top bar — the shortcut out of a long menu |
| Top-left `<` arrow | Go back; highlight it and press to activate |
| Top-right power icon | Restart or power off (shown on the main menu) |

The three side buttons act as context-dependent shortcuts; screens that use them label
them on screen.

If you are unsure whether your hardware works, run **Settings > I/O test**. It shows a
live diagram of the joystick and buttons plus a camera preview, so you can confirm every
input and the camera before trusting the device with a seed.

## Before your first seed

Two settings are worth checking up front, both under **Settings**:

- **Language** — pick yours if it is listed.
- **Camera rotation** — if the camera preview appears upside down or sideways, change
  this. A misoriented camera makes QR scanning fail, and scanning is the only way to get
  data into the device.

Everything else can stay at its defaults. In particular, leave **Bitcoin network** on
Mainnet unless you deliberately want to practice with testnet coins.

### Simple setup, and how to turn it off

This fork ships in **simple setup**: the device assumes a standard single-signature,
Native Segwit wallet — what most wallets use — instead of asking you which arrangement
you want at each step.

That assumption is what keeps the flows short. Connecting to a wallet, for instance,
would otherwise ask three questions in a row (signature type, script type, QR format)
before showing you anything. With only one possible answer to each, all three are
skipped.

It changes nothing about your seed or your security — only which options the device
offers you.

**If you need multisig, Taproot, or another address type**, go to **Settings > Simple
setup** and choose *Show all options*. Every choice comes back, and the questions
return with them. The same screen switches back again, and you can still adjust the
individual settings by hand under **Settings > Advanced**.

> Note: upstream SeedSigner ships with all options enabled. This narrowing is specific
> to this fork.

## Creating a new seed

**Tools** offers two ways to generate one:

- **New seed (dice)** — you roll a physical die and enter each result. 50 rolls for a
  12-word seed, 99 rolls for 24 words. Slow, but the randomness is yours and you can
  verify it independently (see [dice_verification.md](dice_verification.md)).
- **New seed (photo)** — the camera photographs something visually noisy and derives
  randomness from the image.

Either way the device then shows you the seed words, four at a time.

**Write them down before you touch anything else.** Order matters. The device offers to
verify your backup afterwards — do not skip that step. A single mis-transcribed word is
the most common way people permanently lose access to their bitcoin, and the verification
is the only thing that catches it while you can still fix it.

## Loading a seed you already have

Pick **Seeds** from the main menu. With nothing loaded yet it goes straight to the load
options — there is no intermediate list to step through until you have a seed in memory.
You get:

- **Scan a SeedQR** — instant, if you previously made a SeedQR backup.
- **Enter 12-word seed / Enter 24-word seed** — type the words. After a few letters the
  keyboard greys out letters that cannot continue a valid BIP-39 word and offers matching
  words above the three side buttons; press the side button next to a word to accept it.
  You rarely need to type a whole word.

After loading, the device shows a **fingerprint**: a short ID derived from your seed,
displayed as eight hex characters. It is not a secret. Use it to confirm you loaded the
seed you meant to — your wallet software displays the same value for the same seed.

If the words do not form a valid seed phrase, the device says so rather than accepting
them. That check is the BIP-39 checksum, and it catches most typos.

## Connecting to a wallet

Your wallet software needs your *public* keys to watch your balance and build
transactions. **Seeds > [your fingerprint] > Export xpub** displays the xpub as a QR
code for your wallet to scan.

The device warns you first that an xpub is a privacy leak. That warning is accurate and
worth understanding: anyone holding your xpub can see your entire transaction history
forever. They **cannot** spend your bitcoin with it. Treat an xpub as sensitive but not
catastrophic.

You will not be asked to pick a signature type, script type or QR format unless you
have turned [simple setup](#simple-setup-and-how-to-turn-it-off) off. Single Sig with
Native Segwit is what most wallets expect; your wallet's documentation is the authority
if yours differs.

## Signing a transaction

The airgapped round trip:

1. Build the transaction in your wallet software. It produces a QR code (a PSBT).
2. On the device: **Scan**, then point the camera at your wallet's screen. Animated QR
   codes are normal; hold steady until it completes.
3. Load the seed for this wallet if it is not already loaded.
4. **Review what you are signing.** The device shows the amount, the recipient address,
   and the fee. This review is the entire point of a hardware signing device — a
   compromised computer can show you one address and ask you to sign another. Check the
   address on the *device's* screen against where you actually intend to send.
5. **Check the change.** Any amount not sent to the recipient or paid as a fee comes
   back to you as *change*. The device recalculates the change address from your seed
   and shows **Address verified!** when it matches. If it shows **Not verified**, it
   could not check it — for a multisig wallet, load the wallet descriptor and verify
   before continuing. An unverified change output is how funds get silently redirected.
6. Approve. The final screen names the seed that will sign, by fingerprint. The device
   then shows the signed transaction as a QR code.
7. Scan that QR code back into your wallet software, which broadcasts it.

The device never sees your wallet's internet connection and never transmits your seed.

## Verifying a receive address

Before receiving a large amount, use **Tools > Verify address**. Scan the address your
wallet shows you and the device confirms whether that address really belongs to your
seed. This catches malware that swaps the address displayed by your computer.

## Things that trip people up

- **Seeds disappear on power off.** Expected. Load the seed again next time.
- **Settings also reset on power off**, unless you enable **Persistent settings**, which
  requires an SD card and writes your settings (never your seed) to it. It is off by
  default.
- **The device asks you to remove the MicroSD card.** Removing it after boot is what
  makes the device verifiably unable to write anything to disk.
- **"Advanced" settings are genuinely advanced.** If you do not know what a setting does,
  the on-screen help text under its name explains it. If that is still unclear, leave it
  alone.

## Where to get help

- [Project README](../README.md) for hardware, builds and verification
- `python tools/emulator.py` to rehearse a flow on your computer first
- [SeedSigner.com](https://seedsigner.com)
- The upstream project's [Telegram group](https://t.me/joinchat/GHNuc_nhNQjLPWsS)

Practice with a throwaway seed and small amounts before trusting the device with
meaningful funds. Every step above is worth rehearsing once when nothing is at stake.
