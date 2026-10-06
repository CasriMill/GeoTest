import tkinter as tk
from tkinter import messagebox, ttk

from geotest.boundary import fetch_boundary_data, parse_boundary_rings
from geotest.final_map import (
    DEFAULT_FINAL_MAP_PATH,
    DEFAULT_SETTINGS_PATH,
    HexGridSettings,
    load_settings,
    render_final_map_svg,
    save_settings,
)
from geotest.tiling import (
    GridAnalysis,
    analyze_hex_tiling,
    project_boundary_to_km,
)


TARGET_CELL_COUNT = 27


class HexGridWindow:
    def __init__(self, root: tk.Tk, country, rings) -> None:
        self.root = root
        self.country = country
        self.rings = rings
        self.analysis: GridAnalysis | None = None
        self._refresh_id: str | None = None

        root.title("GeoTest — hexagon grid fitting")
        root.geometry("1250x850")
        root.minsize(900, 650)

        controls = ttk.Frame(root, padding=8)
        controls.pack(fill=tk.X)
        try:
            settings = load_settings(DEFAULT_SETTINGS_PATH)
        except FileNotFoundError:
            settings = HexGridSettings()
        self.edge_var = tk.DoubleVar(value=settings.edge_length_km)
        self.east_var = tk.DoubleVar(value=settings.offset_east_km)
        self.north_var = tk.DoubleVar(value=settings.offset_north_km)
        self.rotation_var = tk.DoubleVar(value=settings.rotation_degrees)
        self._add_scale(controls, "Hrana hexu (km)", self.edge_var, 20, 80, 0.5)
        self._add_scale(controls, "Posun východ (km)", self.east_var, -100, 100, 1)
        self._add_scale(controls, "Posun sever (km)", self.north_var, -100, 100, 1)
        self._add_scale(controls, "Rotace (°)", self.rotation_var, 0, 60, 0.5)

        body = ttk.Frame(root, padding=(8, 0, 8, 8))
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, background="white", highlightthickness=1)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._draw)

        statistics = ttk.LabelFrame(body, text="Statistika", padding=10, width=280)
        statistics.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        statistics.pack_propagate(False)
        self.statistics_text = tk.StringVar(value="Počítám síť…")
        ttk.Label(
            statistics,
            textvariable=self.statistics_text,
            justify=tk.LEFT,
            anchor=tk.NW,
            wraplength=250,
        ).pack(fill=tk.X)
        ttk.Label(
            statistics,
            text="Podíl plochy hexu uvnitř ČR",
            wraplength=250,
        ).pack(anchor=tk.W, pady=(14, 4))
        self.cell_list = tk.Listbox(statistics, exportselection=False)
        self.cell_list.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            statistics,
            text="Oranžově: méně než 10 % plochy buňky v ČR.",
            wraplength=250,
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Button(
            statistics,
            text="Uložit nastavení",
            command=self._save_current_settings,
        ).pack(fill=tk.X, pady=(12, 3))
        ttk.Button(
            statistics,
            text="Vytvořit finální SVG",
            command=self._export_final_map,
        ).pack(fill=tk.X, pady=3)

        self._update_analysis()

    def _add_scale(
        self,
        parent: ttk.Frame,
        title: str,
        variable: tk.DoubleVar,
        minimum: float,
        maximum: float,
        resolution: float,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=(6, 3))
        frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)
        scale = tk.Scale(
            frame,
            variable=variable,
            from_=minimum,
            to=maximum,
            resolution=resolution,
            orient=tk.HORIZONTAL,
            showvalue=True,
            length=210,
            command=self._schedule_update,
        )
        scale.pack(fill=tk.X)

    def _schedule_update(self, _value: str | None = None) -> None:
        if self._refresh_id is not None:
            self.root.after_cancel(self._refresh_id)
        self._refresh_id = self.root.after(120, self._update_analysis)

    def _current_settings(self) -> HexGridSettings:
        return HexGridSettings(
            edge_length_km=self.edge_var.get(),
            offset_east_km=self.east_var.get(),
            offset_north_km=self.north_var.get(),
            rotation_degrees=self.rotation_var.get(),
        )

    def _save_current_settings(self) -> None:
        try:
            save_settings(self._current_settings(), DEFAULT_SETTINGS_PATH)
        except (OSError, ValueError) as error:
            messagebox.showerror("Chyba ukládání", str(error), parent=self.root)
            return
        messagebox.showinfo(
            "Nastavení uloženo",
            f"Konfigurace byla uložena do {DEFAULT_SETTINGS_PATH}.",
            parent=self.root,
        )

    def _export_final_map(self) -> None:
        try:
            settings = self._current_settings()
            svg, analysis = render_final_map_svg(self.rings, settings)
            DEFAULT_FINAL_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_FINAL_MAP_PATH.write_text(svg, encoding="utf-8")
            save_settings(settings, DEFAULT_SETTINGS_PATH)
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Chyba exportu finální mapy",
                str(error),
                parent=self.root,
            )
            return
        messagebox.showinfo(
            "Finální mapa vytvořena",
            f"Soubor: {DEFAULT_FINAL_MAP_PATH}\n"
            f"Počet buněk: {len(analysis.cells)}\n"
            f"Minimální využití: "
            f"{min((cell.coverage_ratio for cell in analysis.cells), default=0):.1%}",
            parent=self.root,
        )

    def _update_analysis(self) -> None:
        self._refresh_id = None
        try:
            analysis = analyze_hex_tiling(
                self.country,
                edge_length_km=self.edge_var.get(),
                offset_east_km=self.east_var.get(),
                offset_north_km=self.north_var.get(),
                rotation_degrees=self.rotation_var.get(),
            )
        except Exception as error:
            self.statistics_text.set(f"Výpočet selhal: {error}")
            messagebox.showerror("Chyba výpočtu sítě", str(error), parent=self.root)
            return

        self.analysis = analysis
        ratios = sorted(cell.coverage_ratio for cell in analysis.cells)
        low_count = sum(ratio < 0.10 for ratio in ratios)
        average_ratio = sum(ratios) / len(ratios) if ratios else 0.0
        target_status = (
            "v cíli"
            if len(analysis.cells) <= TARGET_CELL_COUNT
            else f"nad cílem {TARGET_CELL_COUNT}"
        )
        self.statistics_text.set(
            f"Buněk zasahujících do ČR: {len(analysis.cells)} ({target_status})\n"
            f"Pokrytí celé ČR: {'ANO' if analysis.fully_covered else 'NE'}\n"
            f"Nepokrytá plocha: {analysis.uncovered_area_km2:.6f} km²\n"
            f"Buněk s využitím pod 10 %: {low_count}\n"
            f"Nejnižší využití buňky: {min(ratios, default=0):.1%}\n"
            f"Průměrné využití buněk: {average_ratio:.1%}\n\n"
            f"Hrana: {analysis.edge_length_km:.1f} km\n"
            f"Plocha hexu: {analysis.cell_area_km2:.1f} km²\n"
            f"Rotace: {self.rotation_var.get():.1f}°\n"
            f"Posun V/S: {self.east_var.get():.1f} / "
            f"{self.north_var.get():.1f} km"
        )
        self.cell_list.delete(0, tk.END)
        for index, ratio in enumerate(ratios, start=1):
            self.cell_list.insert(
                tk.END,
                f"{index:02d}  {ratio:6.1%} plochy buňky v ČR",
            )
            if ratio < 0.10:
                self.cell_list.itemconfig(index - 1, foreground="#e65100")
        self._draw()

    def _draw(self, _event: tk.Event | None = None) -> None:
        if self.analysis is None:
            return
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        country_bounds = self.country.bounds
        all_bounds = [
            country_bounds,
            *(cell.polygon.bounds for cell in self.analysis.cells),
        ]
        min_x = min(bounds[0] for bounds in all_bounds)
        min_y = min(bounds[1] for bounds in all_bounds)
        max_x = max(bounds[2] for bounds in all_bounds)
        max_y = max(bounds[3] for bounds in all_bounds)
        padding = 24
        factor = min(
            (width - 2 * padding) / max(max_x - min_x, 1e-9),
            (height - 2 * padding) / max(max_y - min_y, 1e-9),
        )

        def canvas_points(points) -> list[float]:
            converted = []
            for x, y in points:
                converted.extend(
                    (
                        padding + (x - min_x) * factor,
                        height - padding - (y - min_y) * factor,
                    )
                )
            return converted

        for polygon in _polygons(self.country):
            canvas.create_polygon(
                canvas_points(polygon.exterior.coords),
                fill="#f8f8f8",
                outline="",
            )
            for interior in polygon.interiors:
                canvas.create_polygon(
                    canvas_points(interior.coords),
                    fill="white",
                    outline="",
                )

        for cell in self.analysis.cells:
            canvas.create_polygon(
                canvas_points(cell.polygon.exterior.coords),
                fill="",
                outline="#e65100" if cell.coverage_ratio < 0.10 else "#555555",
                width=1.3,
            )

        for polygon in _polygons(self.country):
            canvas.create_line(
                canvas_points(polygon.exterior.coords),
                fill="#171717",
                width=1.5,
            )
            for interior in polygon.interiors:
                canvas.create_line(
                    canvas_points(interior.coords),
                    fill="#171717",
                    width=1,
                )

def _polygons(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return [
        polygon
        for component in geometry.geoms
        for polygon in _polygons(component)
    ]


def launch_grid_gui() -> None:
    root = tk.Tk()
    root.title("GeoTest — loading Czechia boundary")
    root.geometry("380x100")
    ttk.Label(root, text="Načítám hranici ČR z OpenStreetMap…", padding=20).pack()
    root.update_idletasks()
    try:
        rings = parse_boundary_rings(fetch_boundary_data())
        country = project_boundary_to_km(rings)
    except Exception as error:
        messagebox.showerror("Chyba načtení hranice ČR", str(error), parent=root)
        root.destroy()
        return
    for widget in root.winfo_children():
        widget.destroy()
    HexGridWindow(root, country, rings)
    root.mainloop()
