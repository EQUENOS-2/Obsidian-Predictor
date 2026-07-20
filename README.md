# Obsidian Predictor
A python script for TMC players that predicts possible obsidian formations in a perimeter.

## Why
But world eaters have AND-gates! What's the point of this script if I can just fix my WE as soon as it gets stuck?

If you're making a large perimeter in an ocean, kelp can really ruin your day. Even if you're using a kelp-proof WE, if just one sweeper gets stuck it's no longer kelp-proof. In modern versions (1.21.5+) each loaded chunk random-ticks, so when you log on to finally fix the sweeper, you may witness the entire layer flooded from multiple kelp growths that occured. Therefore, you really **don't want** your world eater to stop until it removes all oceans. In order to guarantee that, this script might be very handy.

## How to use
1. Download [obi_predict.py](obi_predict.py) and [airlike_blocks.json](airlike_blocks.json) and place them in the same directory. Launching the script requires **Python 3.9+** and the `litemapy` library, which can be installed by running `pip install litemapy` in command prompt.
2. Make a litematica of the region you want to scan. Optionally, you can specify `Corner 1` of your selection at the end of the file name, separating coordinates by space. If you do that, the script will parse that corner. Example: `Terrain Scan 42 -64 42.litematic`.
3. Launch the script. It will ask you to choose a litematica file. If the file name contains corner coordinates, it will parse them right away. If not, it will ask for coordinates of `Corner 1` of your selection.
4. The script will generate xaero waypoints and put them in the folder it's located in. You can then copy them and paste in the corresponding xaero file.

## How to interpret waypoints
Red waypoints indicate lava layers that should be covered. They are grouped, meaning that a single waypoint on a large lava lake indicates that the **entire** surface of that lake should be covered. Some lava lakes have red waypoints on multiple depths. That simply means that it should be drained.

Black waypoints indicate blast-resistant blocks. These waypoints are also grouped. For example, a nether portal will be indicated with just one black waypoint.
