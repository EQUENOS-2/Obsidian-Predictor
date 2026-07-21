import json
import sys
from collections import deque
from enum import IntEnum
from itertools import product
from math import ceil, log
from os.path import abspath
from os.path import join as path_join

import numpy as np
from nbtlib import Compound, File, LongArray


def resource_path(filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return path_join(sys._MEIPASS, filename)  # type: ignore
    return path_join(abspath("."), filename)


WATER: str = "minecraft:water"
LAVA: str = "minecraft:lava"

TOUGH_BLOCKS: set[str] = {
    "minecraft:obsidian",
    "minecraft:vault",
    "minecraft:trial_spawner",
    "minecraft:crying_obsidian",
    "minecraft:ender_chest",
    "minecraft:reinforced_deepslate",
    "minecraft:end_portal_frame",
    "minecraft:anvil",
    "minecraft:chipped_anvil",
    "minecraft:damaged_anvil",
    "minecraft:enchanting_table",
    "minecraft:ancient_debris",
    "minecraft:netherite_block",
    "minecraft:heavy_core",
    "minecraft:respawn_anchor",
}

FRAGILE_BLOCKS: set[str] = {
    "minecraft:glow_lichen",
    "minecraft:mangrove_leaves",
    "minecraft:small_dripleaf",
    "minecraft:big_dripleaf",
    "minecraft:big_dripleaf_stem",
    "minecraft:pointed_dripstone",
}

AIRLIKE: set[str]

with open(resource_path("airlike_blocks.json"), "r") as fp:
    AIRLIKE = set(json.load(fp))


class Color(IntEnum):
    BLACK = 0
    DARK_BLUE = 1
    DARK_GREEN = 2
    DARK_AQUA = 3
    DARK_RED = 4
    DARK_PURPLE = 5
    GOLD = 6
    GRAY = 7
    DARK_GRAY = 8
    BLUE = 9
    GREEN = 10
    AQUA = 11
    RED = 12
    LIGHT_PURPLE = 13
    YELLOW = 14
    WHITE = 15


class BlockState:
    __slots__ = ("_block_id", "properties")

    def __init__(self, block_id: str, properties: dict[str, str]):
        self._block_id: str = block_id
        self.properties: dict[str, str] = properties

    @staticmethod
    def from_nbt(nbt: Compound) -> "BlockState":
        block_id = str(nbt["Name"])
        if "Properties" in nbt:
            properties: dict[str, str] = {
                str(k): str(v) for k, v in nbt["Properties"].items()
            }
        else:
            properties: dict[str, str] = {}
        block = BlockState(block_id, properties)
        return block

    @property
    def id(self) -> str:
        return self._block_id


def get_level(block: BlockState) -> int:
    return int(block.properties["level"])


def is_blast_resistant(block: BlockState) -> bool:
    if block.properties.get("waterlogged") == "true":
        return block.id not in FRAGILE_BLOCKS
    return block.id in TOUGH_BLOCKS


def format_waypoint(
    x: int, y: int, z: int, color: Color, name: str, short_name: str | None = None
) -> str:
    if short_name is None:
        short_name = name[:2]
    return f"waypoint:{name}:{short_name.upper()}:{x}:{y}:{z}:{color}:false:0:gui.xaero_default:false:0:0:false"


class LitematicaBitArrayProxy:
    M: int = (1 << 64) - 1
    nbits: int
    raw_array: LongArray
    _mask: int

    def __init__(self, arr: LongArray, nbits: int) -> None:
        self.nbits = nbits
        self.raw_array = arr
        self._mask = (1 << nbits) - 1

    def __getitem__(self, index) -> int:
        start_offset = index * self.nbits
        start_arr_index = start_offset >> 6
        end_arr_index = ((index + 1) * self.nbits - 1) >> 6
        start_bit_offset = start_offset & 0x3F  # last 6 bits

        if start_arr_index == end_arr_index:
            return (
                self.raw_array[start_arr_index] & self.M
            ) >> start_bit_offset & self._mask
        else:
            end_offset = 64 - start_bit_offset
            val = (self.raw_array[start_arr_index] & self.M) >> start_bit_offset | (
                self.raw_array[end_arr_index] & self.M
            ) << end_offset
            return val & self._mask


class RegionProxy:
    def __init__(
        self,
        width: int,
        height: int,
        length: int,
        palette: list[BlockState],
        bit_array: LitematicaBitArrayProxy,
    ):
        self._width: int = width
        self._height: int = height
        self._length: int = length

        self.width: int = abs(width)
        self.height: int = abs(height)
        self.length: int = abs(length)

        self.palette: list[BlockState] = palette
        self.bit_array: LitematicaBitArrayProxy = bit_array

    def __getitem__(self, point: tuple[int, int, int]) -> BlockState:
        x, y, z = point
        assert (
            0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length
        ), f"Index {point} is out of range; Shape={(self.width, self.height, self.length)}"
        ind = (y * self.width * self.length) + z * self.width + x
        return self.palette[self.bit_array[ind]]

    @staticmethod
    def from_file(path: str) -> "RegionProxy":
        schem = File.load(path, True)
        nbt = next(iter(schem["Regions"].values()))

        palette: list[BlockState] = []
        for block_nbt in nbt["BlockStatePalette"]:
            block = BlockState.from_nbt(block_nbt)
            palette.append(block)

        nbits = max(ceil(log(len(palette), 2)), 2)
        size = nbt["Size"]
        return RegionProxy(
            int(size["x"]),
            int(size["y"]),
            int(size["z"]),
            palette,
            LitematicaBitArrayProxy(nbt["BlockStates"], nbits),
        )


class ObsidianPredictor:
    def __init__(self, x0: int, y0: int, z0: int, region: RegionProxy):
        self.region: RegionProxy = region

        self.origin_x: int = min(x0, x0 + region._width + 1)
        self.origin_y: int = min(y0, y0 + region._height + 1)
        self.origin_z: int = min(z0, z0 + region._length + 1)

        self.size_x: int = region.width
        self.size_y: int = region.height
        self.size_z: int = region.length

        self.layer_matrix: np.ndarray = np.full(
            (self.size_x, self.size_z), 9, dtype=np.int16
        )
        self.marked_lava: set[tuple[int, int]] = set()
        self.blast_resistant_markers: set[tuple[int, int, int]] = set()
        self.markers: list[tuple[int, int, int]] = []

    def to_world_coorinates(self, x: int, y: int, z: int) -> tuple[int, int, int]:
        return self.origin_x + x, self.origin_y + y, self.origin_z + z

    def simulate_water(self, x, y, z, water_level, check_collisions=True) -> None:
        """Simulates liquid propagation from a given water block, updating `layer_matrix`
        with new water values."""
        to_process = deque()
        to_process.append((x, z, water_level))
        terminal_water_level = 7

        while to_process:
            x, z, water_level = to_process.popleft()
            if (
                not (0 <= x < self.size_x)
                or not (0 <= z < self.size_z)
                or water_level >= self.layer_matrix[x, z]
                or (check_collisions and self.region[x, y, z].id not in AIRLIKE)
            ):
                continue

            self.layer_matrix[x, z] = water_level
            # this is needed to stop propagation
            if water_level == terminal_water_level:
                continue
            next_level = (water_level + 1) % 8
            # water flows sideways only if it has a supporting block or it is a source
            if y > 0 and (
                water_level == 0 or self.region[x, y - 1, z].id not in AIRLIKE | {WATER}
            ):
                to_process.append((x + 1, z, next_level))
                to_process.append((x - 1, z, next_level))
                to_process.append((x, z + 1, next_level))
                to_process.append((x, z - 1, next_level))
            elif check_collisions:
                # It is sufficient to stop processing for water of higher level than this.
                # This is the level at which the given stream encountered a height drop.
                terminal_water_level = water_level

    def mark_lava_component(
        self, x: int, y: int, z: int, cache: set[tuple[int, int]]
    ) -> None:
        """Marks all adjacent lava sources at the given y-level"""
        to_process = deque()
        to_process.append((x, z))

        while to_process:
            x, z = to_process.popleft()
            if (
                (x, z) in cache
                or not (0 <= x < self.size_x)
                or not (0 <= z < self.size_z)
            ):
                continue
            block = self.region[x, y, z]
            if block.id == LAVA and get_level(block) == 0:
                cache.add((x, z))
                to_process.append((x + 1, z))
                to_process.append((x - 1, z))
                to_process.append((x, z + 1))
                to_process.append((x, z - 1))

    def try_place_marker(self, x: int, y: int, z: int) -> None:
        """Checks whether a lava source belongs to a group.
        If not, places a marker and saves a new group."""
        if (x, z) in self.marked_lava:
            return
        self.mark_lava_component(x, y, z, self.marked_lava)
        self.markers.append((x, y, z))

    def process_layer(self, y: int) -> None:
        """Inflates all water sources at the given y level,
        processes downwards flow from previous layers, marks flooded lava sources,
        scans for blast resistant blocks."""
        sources = []
        flows = []

        for x, z in product(range(self.size_x), range(self.size_z)):
            block = self.region[x, y, z]
            if block.id == WATER and get_level(block) == 0:
                # we will inflate this as if the eater destroyed all surroundings
                sources.append((x, y, z))
            elif block.id in AIRLIKE and self.layer_matrix[x, z] < 9:
                # we will inherit the flow from directly above
                flows.append((x, y, z))
            elif (
                block.id == LAVA
                and self.layer_matrix[x, z] < 9
                and get_level(block) == 0
            ):
                # mark lava if it has (simulated) water directly above
                self.try_place_marker(x, y, z)
            elif is_blast_resistant(block):
                self.blast_resistant_markers.add((x, y, z))
            self.layer_matrix[x, z] = 9
        # layer_matrix is flushed; simulate water
        for x, y, z in sources:
            self.simulate_water(x, y, z, 0, check_collisions=False)
        for x, y, z in flows:
            self.simulate_water(x, y, z, 8, check_collisions=True)
        # reset lava groups
        self.marked_lava.clear()

    def group_waypoints(
        self, center: tuple[int, int, int]
    ) -> set[tuple[int, int, int]]:
        group: set[tuple[int, int, int]] = set()
        to_process = deque()
        to_process.append(center)

        while to_process:
            x, y, z = to_process.popleft()
            if (
                not (
                    0 <= x < self.size_x
                    and 0 <= y < self.size_y
                    and 0 <= z < self.size_z
                )
                or (x, y, z) not in self.blast_resistant_markers
                or (x, y, z) in group
            ):
                continue
            group.add((x, y, z))
            to_process.append((x + 1, y, z))
            to_process.append((x - 1, y, z))
            to_process.append((x, y + 1, z))
            to_process.append((x, y - 1, z))
            to_process.append((x, y, z + 1))
            to_process.append((x, y, z - 1))

        for point in group:
            self.blast_resistant_markers.discard(point)

        return group

    def get_blast_resistant_markers(self) -> list[tuple[int, int, int]]:
        markers = []
        while self.blast_resistant_markers:
            point = next(iter(self.blast_resistant_markers))
            markers.append(point)
            self.group_waypoints(point)
        return markers

    def save_waypoints(self, path: str) -> None:
        blastres_markers = self.get_blast_resistant_markers()

        with open(path, "w") as fp:
            for x, y, z in self.markers:
                fp.write(
                    f"{format_waypoint(*self.to_world_coorinates(x, y, z), Color.RED, 'X')}\n"
                )

            for x, y, z in blastres_markers:
                fp.write(
                    f"{format_waypoint(*self.to_world_coorinates(x, y, z), Color.BLACK, 'X')}\n"
                )

    def run(self) -> None:
        for y in range(self.size_y - 1, -1, -1):
            print(f"{(self.size_y - y) / self.size_y * 100:.2f} %")
            self.process_layer(y)
