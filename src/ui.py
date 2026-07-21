from threading import Thread
from tkinter import IntVar, Tk, filedialog
from tkinter.ttk import Button, Entry, Frame, Label, Progressbar

from obi_predict import ObsidianPredictor, RegionProxy


def parse_area_origin(path: str) -> tuple[int, int, int] | None:
    try:
        filename = path.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]
        name = filename.rsplit(".", maxsplit=1)[0]
        return tuple(map(int, name.split()[-3:]))  # type: ignore
    except Exception:
        return None


class UserInterface:
    def __init__(self, progress_bar_text: str):
        self.root = Tk()
        self.root.title("Obsidian Predictor")
        self.root.geometry("350x200")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.content = Frame(self.root, padding=10)
        self.content.pack(fill="both", expand=True)

        self.progress_bar_text = progress_bar_text
        self.progress = 0.0
        self.closed = False

        self._done = None
        self._progress_bar = None
        self._coords = None

    def _on_close(self) -> None:
        if self._done is not None:
            self._done.set(0)
        self.closed = True
        self.root.destroy()

    def clear(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()
        self._progress_bar = None

    def request_coordinates(
        self, text: str = "Enter coordinates"
    ) -> tuple[int, int, int]:
        self.clear()

        Label(self.content, text=text).pack(pady=(0, 10))

        entries = {}
        grid = Frame(self.content)
        grid.pack()

        for row, axis in enumerate("XYZ"):
            Label(grid, text=f"{axis}:").grid(row=row, column=0, padx=5, pady=3)
            e = Entry(grid, width=8)
            e.grid(row=row, column=1, padx=5, pady=3)
            entries[axis] = e

        status = Label(self.content)
        status.pack(pady=3)

        self._done = IntVar()

        def submit():
            try:
                coords = tuple(int(entries[a].get()) for a in "XYZ")
            except ValueError:
                status.config(text="Please enter valid integers", foreground="red")
                return

            self._coords = coords
            self._done.set(1)  # type: ignore

        Button(self.content, text="Done", command=submit).pack(pady=5)

        entries["X"].focus()

        self.root.wait_variable(self._done)
        self.clear()

        assert self._coords is not None, "Oh no, coordinates are None!!!"
        return self._coords

    def update_progress_bar(self) -> None:
        if self._progress_bar is None:
            self.clear()

            Label(self.content, text=self.progress_bar_text).pack(pady=(0, 8))

            self._progress_bar = Progressbar(
                self.content,
                orient="horizontal",
                mode="determinate",
                length=250,
                maximum=100,
            )
            self._progress_bar.pack()

            self._progress_label = Label(self.content, text="0%")
            self._progress_label.pack(pady=(5, 0))

        r = max(0.0, min(1.0, self.progress))
        self._progress_bar["value"] = r * 100
        self._progress_label.config(text=f"{r:.1%}")

        self.root.update_idletasks()

    def progress_bar_handler(self):
        self.update_progress_bar()

        if not self.closed:
            self.root.after(100, self.progress_bar_handler)


def run_predictor(predictor: ObsidianPredictor, ui: UserInterface) -> None:
    for y in range(predictor.size_y - 1, -1, -1):
        if ui.closed:
            break
        ui.progress = (predictor.size_y - y) / predictor.size_y
        predictor.process_layer(y)

    ui._on_close()


def main() -> None:
    path = filedialog.askopenfilename(filetypes=[("Litematica", "*.litematic")])
    if not path:
        return print("Terminating...")
    # slightly goofy name parsing but whatever
    filename = path.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]
    name = filename.rsplit(".", maxsplit=1)[0]

    region = RegionProxy.from_file(path)
    origin = parse_area_origin(path)

    ui = UserInterface(f"Removing layers from '{name}'\nand simulating liquids...")

    if origin is None:
        origin = ui.request_coordinates("Input [Corner 1] of your selection")
        if ui.closed:
            return

        ui.clear()
        ui.root.update()

    predictor = ObsidianPredictor(*origin, region)
    Thread(target=run_predictor, args=(predictor, ui), daemon=True).start()
    ui.progress_bar_handler()
    ui.root.mainloop()
    if ui.progress > 1 - 1e-14:
        predictor.save_waypoints(f"{name} waypoints.txt")  # mw$default_1.txt


if __name__ == "__main__":
    main()
