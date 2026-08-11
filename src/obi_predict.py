import json
import sys
from collections import defaultdict, deque
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
BUBBLE_COLUMN: str = "minecraft:bubble_column"

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

LOW_BLAST_RES_TERRAIN: set[str] = {
    "minecraft:dirt",
    "minecraft:grass_block",
    "minecraft:podzol",
    "minecraft:coarse_dirt",
    "minecraft:mycelium",
    "minecraft:rooted_dirt",
    "minecraft:moss_block",
    "minecraft:mud",
    "minecraft:muddy_mangrove_roots",
    "minecraft:crimson_nylium",
    "minecraft:warped_nylium",
    "minecraft:netherrack",
    "minecraft:sand",
    "minecraft:red_sand",
    "minecraft:gravel",
    "minecraft:soul_sand",
    "minecraft:soul_soil",
    "minecraft:calcite",
    "minecraft:clay",
    "minecraft:dripstone_block",
    "minecraft:red_sandstone",
    "minecraft:sandstone",
}

FRAGILE_BLOCKS: set[str] = {
    "minecraft:glow_lichen",
    "minecraft:mangrove_leaves",
    "minecraft:small_dripleaf",
    "minecraft:big_dripleaf",
    "minecraft:big_dripleaf_stem",
    "minecraft:pointed_dripstone",
    "minecraft:sculk_vein",
    "minecraft:tube_coral",
    "minecraft:brain_coral",
    "minecraft:bubble_coral",
    "minecraft:fire_coral",
    "minecraft:horn_coral",
    "minecraft:tube_coral_fan",
    "minecraft:brain_coral_fan",
    "minecraft:bubble_coral_fan",
    "minecraft:fire_coral_fan",
    "minecraft:horn_coral_fan",
    "minecraft:tube_coral_wall_fan",
    "minecraft:brain_coral_wall_fan",
    "minecraft:bubble_coral_wall_fan",
    "minecraft:fire_coral_wall_fan",
    "minecraft:horn_coral_wall_fan",
}

AIRLIKE: set[str]

with open(resource_path("airlike_blocks.json"), "r") as fp:
    AIRLIKE = set(json.load(fp))

LOW_BLAST_RES: set[str] = AIRLIKE | LOW_BLAST_RES_TERRAIN


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
    __slots__ = ("id", "properties")

    def __init__(self, block_id: str, properties: dict[str, str]):
        self.id: str = block_id
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


def get_level(block: BlockState) -> int:
    return int(block.properties["level"])


def is_blast_resistant(block: BlockState) -> bool:
    if block.properties.get("waterlogged") == "true":
        return block.id not in FRAGILE_BLOCKS
    return block.id in TOUGH_BLOCKS


def is_water_source(block: BlockState) -> bool:
    return (
        block.id == WATER
        and get_level(block) == 0
        or block.properties.get("waterlogged") == "true"
        or block.id == BUBBLE_COLUMN
    )


def is_lava_source(block: BlockState) -> bool:
    return block.id == LAVA and get_level(block) == 0


def attracts_vertical_flow(block: BlockState) -> bool:
    return (
        block.id in (WATER, BUBBLE_COLUMN)
        or block.id in AIRLIKE
        # ideally I should check that it's not something like copper grate but I don't care
        or block.properties.get("waterlogged") == "true"
    )


def format_waypoint(
    x: int, y: int, z: int, color: Color, name: str, short_name: str | None = None
) -> str:
    if short_name is None:
        short_name = name[:2]
    return f"waypoint:{name}:{short_name}:{x}:{y}:{z}:{color}:false:0:gui.xaero_default:false:0:0:true"


def is_isolated(point: tuple[int, int], points: list[tuple[int, int]]) -> bool:
    x0, z0 = point
    for x, z in points:
        if abs(x - x0) + abs(z - z0) < 8:
            return False
    return True


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
        self.flooded_lava: dict[int, set[tuple[int, int]]] = defaultdict(set)
        self.focused_flooded_lava: dict[int, set[tuple[int, int]]] = defaultdict(set)

        self.blast_resistant_markers: set[tuple[int, int, int]] = set()
        self.lava_markers: list[tuple[int, int, int]] = []

    def to_world_coorinates(self, x: int, y: int, z: int) -> tuple[int, int, int]:
        return self.origin_x + x, self.origin_y + y, self.origin_z + z

    def simulate_water(self, x, y, z, water_level, check_collisions=True) -> None:
        """Simulates liquid propagation from a given water block, updating `layer_matrix`
        with new water values."""
        to_process = deque()
        to_process.append((x, z, water_level))
        terminal_water_level = 7
        found_lava = False

        while to_process:
            x, z, water_level = to_process.popleft()
            if (
                not (0 <= x < self.size_x)
                or not (0 <= z < self.size_z)
                or water_level >= self.layer_matrix[x, z]
            ):
                continue
            block = self.region[x, y, z]
            if is_lava_source(block):
                self.flooded_lava[y].add((x, z))

            if block.id not in AIRLIKE and check_collisions:
                continue

            self.layer_matrix[x, z] = water_level
            # this is needed to stop propagation
            if water_level == terminal_water_level or y <= 0:
                continue
            next_level = (water_level + 1) % 8
            block_below = self.region[x, y - 1, z]
            # check that water can flow sideways
            if water_level == 0 or not attracts_vertical_flow(block_below):
                to_process.append((x + 1, z, next_level))
                to_process.append((x - 1, z, next_level))
                to_process.append((x, z + 1, next_level))
                to_process.append((x, z - 1, next_level))
            elif check_collisions:
                # It is sufficient to stop processing for water of higher level than this.
                # This is the level at which the given stream encountered a height drop.
                terminal_water_level = water_level
            # update lava marker data
            if is_lava_source(block_below) and (x, z) not in self.flooded_lava:
                self.flooded_lava[y - 1].add((x, z))
                if not found_lava:
                    found_lava = True
                    self.focused_flooded_lava[y - 1].add((x, z))

    def resolve_lava_markers(self, y: int) -> None:
        """Unites `.flooded_lava[y]` into path-connected componentsand distributes markers on them.
        Flushes `.flooded_lava[y]` after being invoked."""
        flooded_lava = self.flooded_lava[y]
        while flooded_lava:
            markers: list[tuple[int, int]] = []
            initial_lava = flooded_lava.pop()
            to_process = deque()
            to_process.append(initial_lava)
            # exhaust the connected component
            while to_process:
                x, z = to_process.popleft()
                for point in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
                    if point in flooded_lava:
                        to_process.append(point)
                        flooded_lava.remove(point)
                    if point in self.focused_flooded_lava[y] and is_isolated(
                        point, markers
                    ):
                        markers.append(point)
            # decide which markers to use
            if not markers:
                markers.append(initial_lava)
            for x, z in markers:
                self.lava_markers.append((x, y, z))

    def process_layer(self, y: int) -> None:
        """Inflates all water sources at the given y level,
        processes downwards flow from previous layers, marks flooded lava sources,
        scans for blast resistant blocks."""
        sources = set()
        flows = []

        for x, z in product(range(self.size_x), range(self.size_z)):
            block = self.region[x, y, z]
            if is_water_source(block):
                # we will inflate this as if the eater destroyed all surroundings
                sources.add((x, y, z))
            elif block.id in LOW_BLAST_RES and self.layer_matrix[x, z] < 9:
                # we will inherit the flow from directly above
                flows.append((x, y, z))
            # bonus check
            if is_blast_resistant(block):
                self.blast_resistant_markers.add((x, y, z))
            # we should flush all values before simulating this layer
            self.layer_matrix[x, z] = 9
        # layer_matrix is flushed; simulate water
        for x, y, z in sources:
            # small optimization to process oceans faster
            if all(
                (x + dx, y, z + dz) in sources
                for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                self.layer_matrix[x, z] = 0
                continue
            # if we're here, it's not an inner water source
            self.simulate_water(x, y, z, 0, check_collisions=False)

        for x, y, z in flows:
            self.simulate_water(x, y, z, 8, check_collisions=True)

        # this also resets lava layer data
        self.resolve_lava_markers(y)

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
            for x, y, z in self.lava_markers:
                fp.write(
                    f"{format_waypoint(*self.to_world_coorinates(x, y, z), Color.RED, 'x')}\n"
                )

            for x, y, z in blastres_markers:
                fp.write(
                    f"{format_waypoint(*self.to_world_coorinates(x, y, z), Color.BLACK, 'x')}\n"
                )

    def run(self) -> None:
        for y in range(self.size_y - 1, -1, -1):
            print(f"{(self.size_y - y) / self.size_y * 100:.2f} %")
            self.process_layer(y)
