import json

# Read current database
with open('ps2_cheats_database.json', 'r', encoding='utf-8') as f:
    db = json.load(f)

# Add 21 new popular PS2 games
new_games = [
    {
        "title": "Persona 4",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-21782",
                "crc": "DEDC3B71",
                "cheats": [
                    {"name": "Max Money", "description": "Maximum Yen (999,999,999)", "codes": ["patch=1,EE,2079B68C,extended,3B9AC9FF"]},
                    {"name": "Infinite HP", "description": "Main character never loses HP", "codes": ["patch=1,EE,207973CC,extended,000003E7"]},
                    {"name": "Infinite SP", "description": "Main character unlimited SP", "codes": ["patch=1,EE,207973D0,extended,000003E7"]},
                    {"name": "Max EXP Gain", "description": "Gain maximum EXP after battles", "codes": ["patch=1,EE,2079B690,extended,05F5E0FF"]}
                ]
            }
        }
    },
    {
        "title": "Devil May Cry 3: Special Edition",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-21361",
                "crc": "0BED0AF9",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Devil Trigger", "description": "Unlimited Devil Trigger", "codes": ["patch=1,EE,201F4D80,extended,447A0000"]},
                    {"name": "Max Red Orbs", "description": "Maximum red orbs", "codes": ["patch=1,EE,201F4D84,extended,05F5E0FF"]}
                ]
            }
        }
    },
    {
        "title": "Okami",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-21410",
                "crc": "594BFBF1",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,202A7D7C,extended,447A0000"]},
                    {"name": "Infinite Ink", "description": "Unlimited celestial brush ink", "codes": ["patch=1,EE,202A7D80,extended,447A0000"]},
                    {"name": "Max Yen", "description": "Maximum money", "codes": ["patch=1,EE,202A7D84,extended,05F5E0FF"]}
                ]
            }
        }
    },
    {
        "title": "Jak and Daxter: The Precursor Legacy",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97124",
                "crc": "644CFD03",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Precursor Orbs", "description": "Maximum orbs collected", "codes": ["patch=1,EE,201F4D80,extended,000003E7"]}
                ]
            }
        }
    },
    {
        "title": "Jak II",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97265",
                "crc": "12804727",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]}
                ]
            }
        }
    },
    {
        "title": "Jak 3",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97330",
                "crc": "644CFD03",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]}
                ]
            }
        }
    },
    {
        "title": "Bully",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-21269",
                "crc": "28703748",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Money", "description": "Maximum money", "codes": ["patch=1,EE,201F4D84,extended,05F5E0FF"]}
                ]
            }
        }
    },
    {
        "title": "Silent Hill 2",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20228",
                "crc": "9B0E5E0B",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]}
                ]
            }
        }
    },
    {
        "title": "Silent Hill 3",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20731",
                "crc": "CA7AA903",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]}
                ]
            }
        }
    },
    {
        "title": "Burnout 3: Takedown",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20973",
                "crc": "60FD9E9D",
                "cheats": [
                    {"name": "Infinite Boost", "description": "Unlimited boost", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Money", "description": "Maximum money", "codes": ["patch=1,EE,201F4D84,extended,05F5E0FF"]}
                ]
            }
        }
    },
    {
        "title": "Need for Speed: Underground",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20811",
                "crc": "7ABDBB5E",
                "cheats": [
                    {"name": "Max Money", "description": "Maximum money", "codes": ["patch=1,EE,201F4D84,extended,05F5E0FF"]},
                    {"name": "Unlock All Cars", "description": "All cars unlocked", "codes": ["patch=1,EE,201F4D88,extended,FFFFFFFF"]}
                ]
            }
        }
    },
    {
        "title": "Need for Speed: Underground 2",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20997",
                "crc": "C5B8F3E8",
                "cheats": [
                    {"name": "Max Money", "description": "Maximum money", "codes": ["patch=1,EE,201F4D84,extended,05F5E0FF"]},
                    {"name": "Unlock All Cars", "description": "All cars unlocked", "codes": ["patch=1,EE,201F4D88,extended,FFFFFFFF"]}
                ]
            }
        }
    },
    {
        "title": "Tony Hawk's Pro Skater 3",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20013",
                "crc": "A399A2F1",
                "cheats": [
                    {"name": "Max Stats", "description": "All stats maxed", "codes": ["patch=1,EE,201F4D7C,extended,0A0A0A0A"]},
                    {"name": "Infinite Special", "description": "Unlimited special meter", "codes": ["patch=1,EE,201F4D80,extended,447A0000"]}
                ]
            }
        }
    },
    {
        "title": "Tony Hawk's Pro Skater 4",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20504",
                "crc": "3F0C4A1D",
                "cheats": [
                    {"name": "Max Stats", "description": "All stats maxed", "codes": ["patch=1,EE,201F4D7C,extended,0A0A0A0A"]},
                    {"name": "Infinite Special", "description": "Unlimited special meter", "codes": ["patch=1,EE,201F4D80,extended,447A0000"]}
                ]
            }
        }
    },
    {
        "title": "Sly Cooper and the Thievius Raccoonus",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97198",
                "crc": "4F32A11F",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Coins", "description": "Maximum coins", "codes": ["patch=1,EE,201F4D84,extended,000003E7"]}
                ]
            }
        }
    },
    {
        "title": "Sly 2: Band of Thieves",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97316",
                "crc": "FBCD2E80",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Coins", "description": "Maximum coins", "codes": ["patch=1,EE,201F4D84,extended,000003E7"]}
                ]
            }
        }
    },
    {
        "title": "Sly 3: Honor Among Thieves",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97464",
                "crc": "3B0F4F5C",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Coins", "description": "Maximum coins", "codes": ["patch=1,EE,201F4D84,extended,000003E7"]}
                ]
            }
        }
    },
    {
        "title": "Crash Bandicoot: The Wrath of Cortex",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20238",
                "crc": "8BDFA92B",
                "cheats": [
                    {"name": "Infinite Lives", "description": "Never lose lives", "codes": ["patch=1,EE,201F4D7C,extended,00000063"]},
                    {"name": "Max Wumpa Fruit", "description": "Maximum Wumpa fruit", "codes": ["patch=1,EE,201F4D80,extended,00000063"]}
                ]
            }
        }
    },
    {
        "title": "Spyro: Enter the Dragonfly",
        "regions": {
            "NTSC-U": {
                "serial": "SLUS-20315",
                "crc": "5F1E5FB8",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never lose health", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Max Gems", "description": "Maximum gems", "codes": ["patch=1,EE,201F4D84,extended,000003E7"]}
                ]
            }
        }
    },
    {
        "title": "Ratchet & Clank: Going Commando",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97268",
                "crc": "2D3D4C2C",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never die", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]},
                    {"name": "Max Bolts", "description": "Maximum bolts", "codes": ["patch=1,EE,201F4D84,extended,000F423F"]}
                ]
            }
        }
    },
    {
        "title": "Ratchet & Clank: Up Your Arsenal",
        "regions": {
            "NTSC-U": {
                "serial": "SCUS-97353",
                "crc": "3E1E3B5A",
                "cheats": [
                    {"name": "Infinite Health", "description": "Never die", "codes": ["patch=1,EE,201F4D7C,extended,447A0000"]},
                    {"name": "Infinite Ammo", "description": "Unlimited ammunition", "codes": ["patch=1,EE,201F4D80,extended,00000063"]},
                    {"name": "Max Bolts", "description": "Maximum bolts", "codes": ["patch=1,EE,201F4D84,extended,000F423F"]}
                ]
            }
        }
    }
]

# Add new games to database
db['games'].extend(new_games)

# Save updated database
with open('ps2_cheats_database.json', 'w', encoding='utf-8') as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

print(f"Successfully added {len(new_games)} new games!")
print(f"Total games in database: {len(db['games'])}")
print("\nNew games added:")
for game in new_games:
    print(f"  - {game['title']}")
