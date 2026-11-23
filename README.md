# Valheim Cheat Flag Cleaner

Removes the permanent **"Achievement progress is permanently disabled for this character due to dev command usage"** flag from a Valheim 1.0 character.

**Use it in your browser:** https://bbckr.github.io/valheim-cheatflag-cleaner/

Your save never leaves your computer. The website does everything locally in your browser. There's also a Python script below if you'd rather run it yourself.

---

## Why I made this

When Valheim 1.0 came out, my main character got flagged as a cheater. I never used dev commands in my actual playthrough. The only time I touched them was messing around in a separate test world. But the flag is stored on the character, not the world, so it followed me everywhere. Every time I loaded into my real world, I got told my achievements were permanently disabled because of dev command usage.

Valheim's own fix is to type `yesiuseddevcommandsbutiwantmyachievementsanyway` in the console. That turns achievements back on, but the warning still shows. You're basically admitting to cheating in a playthrough that was completely legit, and the character is still marked. I didn't want that. I wanted my character back the way it was.

So I dug into the `.fch` save file, found where the flag is stored, and wrote this to clear it properly. If you're in the same situation, it should fix yours too.

---

## Quick start (browser)

1. **Close Valheim.**
2. Open your character folder. Paste this into the Windows Explorer address bar:
   ```
   %USERPROFILE%\AppData\LocalLow\IronGate\Valheim\characters_local
   ```
3. **Back up** your `yourname.fch` file.
4. Go to the [website](https://bbckr.github.io/valheim-cheatflag-cleaner/), drop in `yourname.fch`, and click **Clean & download**.
5. Put the downloaded file back in the folder, replacing the old one (same file name).
6. Start Valheim.

## Quick start (command line)

You need Python 3.8 or newer. Nothing else to install.

```bash
# see your characters and which ones are flagged
python valheim_cheatflag.py list

# check one character (doesn't change anything)
python valheim_cheatflag.py scan moonkej

# clear the flag (makes a backup first)
python valheim_cheatflag.py clean moonkej
```

You can pass either a character's file name (it looks in the normal save folders) or a full path to a `.fch` file.

| Option | What it does |
|---|---|
| `-y`, `--yes` | Don't ask for confirmation |
| `--no-backup` | Skip the backup copy (not recommended) |
| `--keep-stat` | Clear the flag but leave the "Cheats" number in your stats alone |

Backups are saved next to the original as `yourname.fch.precleanup-<date>-<time>`. To undo, rename one back to `yourname.fch`.

---

## Where the save files are

| Platform | Folder |
|---|---|
| Windows | `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\characters_local` |
| Windows (Steam Cloud) | `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\characters` |
| Linux / Steam Deck | `~/.config/unity3d/IronGate/Valheim/characters_local` |
| macOS | `~/Library/Application Support/IronGate/Valheim/characters_local` |

Use the `.fch` file, not `.fch.old`.

**Steam Cloud:** if your character is in `characters`, Steam may put the old file back. Turn off Steam Cloud for Valheim (right-click Valheim → Properties → General), replace the file, launch the game once, then turn Steam Cloud back on.

---

## What it changes

Three things in the character file:

1. The character's **used-cheats flag** → off
2. The **Cheats** counter in your character stats → 0 (skip with `--keep-stat`)
3. The file's **SHA-512 checksum** → recalculated so the game accepts the file

Nothing else is touched. Skills, inventory, map, appearance and the rest stay exactly as they were.

## Still seeing a warning?

Valheim has a few different cheat marks, and this tool fixes the character one. If you still see something, check which message it is:

- **"…temporarily disabled… due to possession of cheated items"**: you're carrying a spawned item. Drop it or put it in a chest.
- **"…permanently disabled for this world…"**: the world is flagged, not your character. That's stored in the world save, which this tool doesn't edit.
- Using most dev commands again (`spawn`, `god`, `debugmode`, …) will set the flag again.

## Will I get the achievements I missed?

No. Valheim doesn't hand out achievements after the fact. Anything you completed while flagged has to be done again after cleaning, like beating a boss again (you can re-summon them at their altars), crafting the item again, or visiting the place again. This tool only makes sure that from now on, what you do actually counts.

---

## How it works

A `.fch` file is laid out like this:

```
uint32   data length
byte[]   data
uint32   hash length (64)
byte[64] SHA-512 of data
```

Inside the data, the character's stats are near the start (a count, then one float per stat; `Cheats` is the 5th). Further in, after the per-world map data, is the profile header:

```
string  character name
int64   player ID
string  start seed
bool    used cheats      <- the flag
int64   date created     (unix seconds)
```

The map data before it varies in size, so the tool doesn't use fixed offsets. It looks for the one spot where all five fields line up: a valid name, an ID, a seed string, a 0/1 flag, and a creation date between 2021 and now. If it finds zero or more than one match, it stops and changes nothing.

Tested on character save version 47 (Valheim 1.0.x).

## Running the tests

```bash
python -m unittest discover tests
```

## Disclaimer

Unofficial fan tool, not affiliated with Iron Gate or Coffee Stain. Back up your saves. Use at your own risk.

## License

[MIT](LICENSE)
