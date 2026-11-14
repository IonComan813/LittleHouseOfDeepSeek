# LPC art used in the house picture

These sprite sheets come from the Liberated Pixel Cup (LPC) collection on OpenGameArt.
They are **not** under the project's Apache-2.0 licence: each keeps its own licence below
(CC-BY-SA 3.0 / GPL 3.0 / CC-BY 4.0 — redistribution allowed with attribution; changes to
the art itself must be shared under the same terms). The files are unmodified copies; the
house cuts single pictures out of them at run time (`littlehouse/sprites.py`).

| File here | From | Licence | Artists |
| --- | --- | --- | --- |
| `sofas_casual.png`, `beds_single_a.png`, `chairs_sofa.png`, `tables.png`, `decorative_furniture.png` | [LPC Revised Base Object Kit](https://opengameart.org/content/lpc-revised-base-object-kit) (Furniture) | CC-BY-SA 3.0 | Lanea Zimmerman (Sharm), BlueCarrot16; adjustments, side/back views and recolours by Eliza Wyatt (Death's Darling) |
| `cabinets.png` | LPC Revised Base Object Kit (Storage) | CC-BY-SA 3.0 | Lanea Zimmerman; variants and recolours by Eliza Wyatt |
| `planters.png`, `flowers.png`, `paintings.png` | LPC Revised Base Object Kit (Decoration) | CC-BY-SA 3.0 | Lanea Zimmerman, Eliza Wyatt; recolours by Eliza Wyatt |
| `lighting.png` | LPC Revised Base Object Kit (Lighting & Fire) | CC-BY-SA 3.0 | Lanea Zimmerman; adjustments and recolours by Eliza Wyatt |
| `house_interior.png` | [[LPC] House interior and decorations](https://opengameart.org/content/lpc-house-interior-and-decorations) | CC-BY-SA 3.0 / GPL 3.0 / GPL 2.0 | Reemax (Tuomo Untinen), based on LPC base tiles by Lanea Zimmerman (Sharm); some items by Hyptosis, Daniel Eddeland, bluecarrot16 |
| `farming_plants.png`, `farming_plowed_soil.png` | [[LPC] Farming tilesets, magic animations and UI elements](https://opengameart.org/content/lpc-farming-tilesets-magic-animations-and-ui-elements) | CC-BY-SA 3.0 / GPL 3.0 | Daniel Eddeland |

| `chests.png` | LPC Revised Base Object Kit (Storage) | CC-BY-SA 3.0 | Lanea Zimmerman; variants and recolours by Eliza Wyatt |
| `terrain_atlas.png` | [LPC Tile Atlas](https://opengameart.org/content/lpc-tile-atlas) (adrix89) | CC-BY-SA 3.0 / GPL 3.0 | Lanea Zimmerman (Sharm), Daniel Eddeland, Casper Nilsson, Johann Charlot, Skyler Robert Colladay and other LPC participants (see the atlas's Attribution.txt) |
| `cats.png` | [[LPC] Cats and Dogs](https://opengameart.org/content/lpc-cats-and-dogs) | CC-BY 3.0 / CC-BY-SA 3.0 / GPL 3.0 / OGA-BY 3.0 | bluecarrot16 |
| `character/body_female_walk.png` | [Universal LPC Spritesheet Character Generator](https://github.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator) `body/bodies/female` ([LPC character bases](https://opengameart.org/content/lpc-character-bases)) | OGA-BY 3.0 / CC-BY-SA 3.0 / GPL 3.0 | Benjamin K. Smith (BenCreating), bluecarrot16, TheraHedwig, Evert, MuffinElZangano, Durrani, Pierre Vigier (pvigier), ElizaWy, Matthew Krohn (makrohn), Johannes Sjölund (wulax), Stephen Challener (Redshrike) |
| `character/head_female_walk.png` | same generator, `head/heads/human/female` | OGA-BY 3.0 / CC-BY-SA 3.0 / GPL 3.0 | bluecarrot16, Benjamin K. Smith (BenCreating), Stephen Challener (Redshrike) |
| `character/hair_long_walk.png` | same generator, `hair/long/adult` | CC-BY-SA 3.0 / GPL 3.0 | JaidynReiman, Manuel Riecke (MrBeast) |
| `character/blouse_blue_walk.png` | same generator, `torso/clothes/blouse/female` (blue) | OGA-BY 3.0 / CC-BY-SA 3.0 / GPL 3.0 | bluecarrot16, ElizaWy, Lanea Zimmerman (Sharm) |
| `character/apron_full_white_walk.png` | same generator, `torso/aprons/apron_full/female` (white); [LPC clothing updates](http://opengameart.org/content/lpc-clothing-updates) | OGA-BY 3.0 / GPL 3.0 | ElizaWy, bluecarrot16 |
| `character/skirt_plain_walk.png` | same generator, `legs/skirts/plain/thin`; [LPC Medieval fantasy character sprites](https://opengameart.org/content/lpc-medieval-fantasy-character-sprites) | OGA-BY 3.0 / CC-BY-SA 3.0 / GPL 3.0 | bluecarrot16, Pierre Vigier (pvigier), Johannes Sjölund (wulax), Ahmad3366, JaidynReiman |

The resident is assembled from the `character/` layers at run time (`sprites.resident`): the
hair and skirt are recoloured blue, and her cowlick, whale tail and the little whale on her
apron are drawn by code. The cat is the golden coat from `cats.png`.

The Object Kit pages also credit the related LPC packs it builds on:
[LPC Upholstery](https://opengameart.org/content/lpc-upholstery),
[LPC Interior Castle Tiles](https://opengameart.org/content/lpc-interior-castle-tiles),
[LPC Dungeon Elements](https://opengameart.org/content/lpc-dungeon-elements).
LPC base assets: http://lpc.opengameart.org/static/lpc-style-guide/assets.html

Everything else in the picture (walls, floors, the fence, the fridge, the mailbox, the
rug and desk, spinach / scallions / pumpkins / strawberries, effects, weather and the HUD)
is drawn by code in `render.py`.
