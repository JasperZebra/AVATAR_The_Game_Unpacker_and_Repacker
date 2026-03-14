[![GitHub release (latest by date)](https://img.shields.io/github/v/release/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker?style=for-the-badge&logo=github&color=00ffff&logoColor=white&labelColor=1a4d66)](https://github.com/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker)
[![Total Downloads](https://img.shields.io/github/downloads/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker/total?style=for-the-badge&logo=github&color=00ffff&logoColor=white&labelColor=1a4d66)](https://github.com/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker)
[![Platform](https://img.shields.io/badge/platform-windows-00ffff?style=for-the-badge&logo=windows&logoColor=00ffff&labelColor=1a4d66)](https://github.com/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker)
[![Made for](https://img.shields.io/badge/made%20for-2009_AVATAR:_The_Game-00ffff?style=for-the-badge&logo=gamepad&logoColor=00ffff&labelColor=1a4d66)](https://github.com/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker)
[![Tool Type](https://img.shields.io/badge/type-PAK%20unpacker%20%26%20repacker-00ffff?style=for-the-badge&logo=package&logoColor=00ffff&labelColor=1a4d66)](https://github.com/JasperZebra/AVATAR_The_Game_Unpacker_and_Repacker)

# AVATAR: The Game Unpacker & Repacker
This unpacker and repacker has support for both 32 Bit and 64 Bit systems.

## Features

- **Unpack** — extracts all files from a PAK archive, restoring original folder structure.
- **Repack** — packs a folder back into a valid PAK file.
- **Parallel extraction** — uses all available CPU cores for fast decompression.
- **Drag-and-drop** — drop a `.pak` file to unpack, or drop a folder to repack.
- **x86 and x64 support** — automatically loads the correct LZO DLL for your system.

## How to Use

1. Find the `.pak` file you want to extract.
2. Drag and drop it onto `PAK_Tool_x64.exe` if on a 64 bit system, or onto `PAK_Tool_x86.exe` if on a 32 bit system.
3. A folder will be created in the same location as the `.pak` file, with the same name.
4. All files will be extracted into that folder.

## Repacking a Folder into a PAK File

1. Make sure your modded files are inside a folder with the correct subfolder structure.
2. Drag and drop the extracted folder onto `PAK_Tool_x64.exe` if on a 64 bit system, or onto `PAK_Tool_x86.exe` if on a 32 bit system.
3. A `.pak` file will be created in the same location as the folder, with the same name.
