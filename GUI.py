import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime, timedelta
import calendar

import API_Calls as api

# ---- Static choices ----
SUBSTATION_VALUES = ["24", "26", "27", "28", "31", "32", "33", "34", "35"]
LINE_VALUES = ["Line 1", "Line 2", "Line 3"]
TRANSFORMER_VALUES = ["Transformer 1", "Transformer 2", "Transformer 3"]
BUS_VALUES = ["bus 1", "bus 2", "bus 3"]
FEEDER_VALUES = ["8-27.11", "8-27.12", "8-27.13", "8-27.14"]

FIELDS = [
    ("Substation", SUBSTATION_VALUES),
    ("Line", LINE_VALUES),
    ("Transformer", TRANSFORMER_VALUES),
    ("Bus", BUS_VALUES),
    ("Feeder", FEEDER_VALUES),
]

PREVIOUS_RANGES = [
    ("Q2 2025", ("2025-04-01", "2025-06-30")),
    ("June 2025", ("2025-06-01", "2025-06-30")),
]

def to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def parse_iso(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

# ---- Simple calendar popup ----
class DatePickerPopup(tk.Toplevel):
    def __init__(self, master, initial: date, on_pick):
        super().__init__(master)
        self.title("Select Date")
        self.transient(master)
        self.resizable(False, False)
        self.on_pick = on_pick
        self.selected = initial or date.today()
        self.grab_set()

        self.var_year = tk.IntVar(value=self.selected.year)
        self.var_month = tk.IntVar(value=self.selected.month)

        nav = ttk.Frame(self); nav.pack(fill="x", padx=8, pady=6)
        ttk.Button(nav, text="◀", width=2, command=self.prev_month).pack(side="left")
        self.lbl_month = ttk.Label(nav, text=self._month_year_text(), width=18, anchor="center")
        self.lbl_month.pack(side="left", expand=True)
        ttk.Button(nav, text="▶", width=2, command=self.next_month).pack(side="right")

        hdr = ttk.Frame(self); hdr.pack(fill="x", padx=8)
        for wd in ["Mo","Tu","We","Th","Fr","Sa","Su"]:
            ttk.Label(hdr, text=wd, width=3, anchor="center").pack(side="left", padx=2)

        self.days_frame = ttk.Frame(self); self.days_frame.pack(padx=8, pady=(2,8))
        self._draw_days()

    def _month_year_text(self):
        return f"{calendar.month_name[self.var_month.get()]} {self.var_year.get()}"

    def prev_month(self):
        y, m = self.var_year.get(), self.var_month.get()
        m -= 1
        if m < 1: y, m = y-1, 12
        self.var_year.set(y); self.var_month.set(m)
        self.lbl_month.config(text=self._month_year_text()); self._draw_days()

    def next_month(self):
        y, m = self.var_year.get(), self.var_month.get()
        m += 1
        if m > 12: y, m = y+1, 1
        self.var_year.set(y); self.var_month.set(m)
        self.lbl_month.config(text=self._month_year_text()); self._draw_days()

    def _draw_days(self):
        for w in self.days_frame.winfo_children(): w.destroy()
        y, m = self.var_year.get(), self.var_month.get()
        cal = calendar.Calendar(firstweekday=0)
        today = date.today()
        row = col = 0
        for d in cal.itermonthdates(y, m):
            if col == 7: col = 0; row += 1
            btn_text = " " if d.month != m else str(d.day)
            btn = ttk.Button(self.days_frame, text=btn_text, width=3)
            btn.grid(row=row, column=col, padx=2, pady=2)
            if d.month != m:
                btn.state(["disabled"])
            else:
                if d == today: ttk.Style(self).configure("Today.TButton")
                btn.configure(command=lambda dd=d: self._pick(dd))
            col += 1

    def _pick(self, d: date):
        if callable(self.on_pick): self.on_pick(d)
        self.destroy()

class DeviceShuttleApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Device Selection Shuttle")
        self.geometry("1180x660")
        self.minsize(1100, 600)

        self.api_config = api.APIConfig(
            base_url="https://your-pi-web-api-server/piwebapi",
            use_kerberos=False,
            username="username",
            password="password",
        )

        # Top: Date range + Interval
        self.prev_ranges = PREVIOUS_RANGES[:]
        self.var_prev_range = tk.StringVar(value=self.prev_ranges[0][0] if self.prev_ranges else "")
        self.var_start = tk.StringVar(value=to_iso(date.today()))
        self.var_end = tk.StringVar(value=to_iso(date.today()))
        self.var_date_preset = tk.StringVar(value="")

        self.var_interval_value = tk.StringVar(value="15")
        self.var_interval_unit = tk.StringVar(value="minute")
        self.var_interval_preset = tk.StringVar(value="")

        # Middle: device pickers
        self.current_values = {name: tk.StringVar(value="") for name, _ in FIELDS}

        # Right column (new)
        self.var_ds_min = tk.BooleanVar(value=False)
        self.var_ds_avg = tk.BooleanVar(value=False)    # global Average
        self.var_ds_max = tk.BooleanVar(value=True)     # default checked

        self.var_output_unit = tk.StringVar(value="Amp")
        self.var_coincidental = tk.BooleanVar(value=False)
        self.var_multi_phase = tk.BooleanVar(value=False)
        self.var_multi_avg = tk.BooleanVar(value=False) # Average under Multi Phase

        self._build_ui()

    # ------------- UI -------------
    def _build_ui(self):
        # Grid: top controls (row 0), middle row (shuttle + right column), bottom preview (row 2)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=1)
        self.columnconfigure(3, weight=0)  # right-most column
        self.rowconfigure(1, weight=1)

        # --- Top Left: Date Range ---
        top_left = ttk.LabelFrame(self, text="Select Date Range")
        top_left.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=(10,6))
        for i in range(4): top_left.columnconfigure(i, weight=1)

        ttk.Label(top_left, text="Previous Date Ranges:").grid(row=0, column=0, sticky="e", padx=(10,6), pady=6)
        self.cb_prev = ttk.Combobox(top_left, state="readonly",
                                    values=[label for (label, _) in self.prev_ranges],
                                    textvariable=self.var_prev_range)
        self.cb_prev.grid(row=0, column=1, sticky="ew", padx=(0,10), pady=6)
        ttk.Button(top_left, text="Apply", command=self.apply_previous_range)\
            .grid(row=0, column=2, sticky="w", padx=(0,10), pady=6)

        ttk.Label(top_left, text="Start Date:").grid(row=1, column=0, sticky="e", padx=(10,6), pady=6)
        self.ent_start = ttk.Entry(top_left, textvariable=self.var_start, width=14)
        self.ent_start.grid(row=1, column=1, sticky="w", padx=(0,6), pady=6)
        ttk.Button(top_left, text="📅", width=3, command=lambda: self.open_date_picker(self.var_start))\
            .grid(row=1, column=2, sticky="w", padx=(0,10), pady=6)

        ttk.Label(top_left, text="End Date:").grid(row=2, column=0, sticky="e", padx=(10,6), pady=6)
        self.ent_end = ttk.Entry(top_left, textvariable=self.var_end, width=14)
        self.ent_end.grid(row=2, column=1, sticky="w", padx=(0,6), pady=6)
        ttk.Button(top_left, text="📅", width=3, command=lambda: self.open_date_picker(self.var_end))\
            .grid(row=2, column=2, sticky="w", padx=(0,10), pady=6)

        presets = ttk.Frame(top_left); presets.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(4,8))
        ttk.Label(presets, text="Presets:").pack(side="left", padx=(0,8))
        for val, label in [("yesterday","Yesterday"), ("7","Last 7 Days"), ("30","Last 30 Days"), ("365","Past 12 Months")]:
            ttk.Radiobutton(presets, text=label, value=val, variable=self.var_date_preset,
                            command=self.apply_date_preset).pack(side="left", padx=6)

        # --- Top Middle-Right: Interval ---
        top_right = ttk.LabelFrame(self, text="Select Time Interval")
        top_right.grid(row=0, column=2, sticky="nsew", padx=(0,10), pady=(10,6))
        for i in range(4): top_right.columnconfigure(i, weight=1)

        ttk.Label(top_right, text="Interval:").grid(row=0, column=0, sticky="e", padx=(10,6), pady=6)
        self.spn_interval = ttk.Spinbox(top_right, from_=0, to=60, increment=1,
                                        textvariable=self.var_interval_value, width=6)
        self.spn_interval.grid(row=0, column=1, sticky="w", padx=(0,6), pady=6)
        self.cb_unit = ttk.Combobox(top_right, state="readonly",
                                    values=["minute", "hour"], textvariable=self.var_interval_unit, width=8)
        self.cb_unit.grid(row=0, column=2, sticky="w", padx=(0,10), pady=6)

        int_presets = ttk.Frame(top_right); int_presets.grid(row=1, column=0, columnspan=4, sticky="w", padx=10, pady=(4,8))
        ttk.Label(int_presets, text="Presets:").pack(side="left", padx=(0,8))
        for val, label in [("15m","15 minutes"), ("hourly","Hourly"), ("daily","Daily"), ("weekly","Weekly"), ("monthly","Monthly")]:
            ttk.Radiobutton(int_presets, text=label, value=val, variable=self.var_interval_preset,
                            command=self.apply_interval_preset).pack(side="left", padx=6)

        # --- Middle Left: Device selection + arrows + selected (shuttle) ---
        self.columnconfigure(0, weight=1, minsize=260)
        self.columnconfigure(1, weight=0, minsize=60)
        self.columnconfigure(2, weight=1, minsize=360)

        left = ttk.LabelFrame(self, text="Device selection")
        left.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        left.columnconfigure(1, weight=1)
        self.combos = {}
        for r, (label, values) in enumerate(FIELDS):
            ttk.Label(left, text=label + ":").grid(row=r, column=0, padx=(10, 6), pady=8, sticky="e")
            combo = ttk.Combobox(left, values=values, textvariable=self.current_values[label], state="readonly")
            combo.grid(row=r, column=1, padx=(0, 10), pady=8, sticky="ew")
            self.combos[label] = combo

        mid = ttk.Frame(self); mid.grid(row=1, column=1, sticky="ns", pady=6)
        for r, (label, _) in enumerate(FIELDS):
            ttk.Button(mid, text="➜", width=3, command=lambda key=label: self.add_selection(key))\
                .grid(row=r, column=0, padx=6, pady=8, sticky="n")

        right = ttk.LabelFrame(self, text="Selected Devices")
        right.grid(row=1, column=2, sticky="nsew", padx=(0, 10), pady=6)
        right.rowconfigure(0, weight=1); right.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(right, columns=("key", "value"), show="headings", height=8)
        self.tree.heading("key", text="Field"); self.tree.heading("value", text="Value")
        self.tree.column("key", width=140, anchor="w"); self.tree.column("value", width=240, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))
        yscroll = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set); yscroll.grid(row=0, column=1, sticky="ns", pady=(10, 6))

        btns = ttk.Frame(right); btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))
        for i in range(3): btns.columnconfigure(i, weight=1)
        ttk.Button(btns, text="Remove Selected", command=self.remove_selected).grid(row=0, column=0, sticky="ew", padx=4)
        ttk.Button(btns, text="Clear All", command=self.clear_all).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(btns, text="Build REST Query", command=self.build_rest_query).grid(row=0, column=2, sticky="ew", padx=4)

        # --- NEW: Far Right Column with single stacked column ---
        far_right = ttk.LabelFrame(self, text="Options")
        far_right.grid(row=1, column=3, sticky="nsew", padx=(0,10), pady=6)
        far_right.columnconfigure(0, weight=1)

        # Data Sets (multi-checkbox)
        ds_frame = ttk.LabelFrame(far_right, text="Data Sets")
        ds_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        ttk.Checkbutton(ds_frame, text="Minimum", variable=self.var_ds_min).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(ds_frame, text="Average", variable=self.var_ds_avg).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(ds_frame, text="Maximum", variable=self.var_ds_max).grid(row=2, column=0, sticky="w", padx=6, pady=2)

        # Output Unit
        unit_frame = ttk.LabelFrame(far_right, text="Output Unit")
        unit_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        self.cb_output_unit = ttk.Combobox(unit_frame, state="readonly",
                                           values=["Amp", "MVW"], textvariable=self.var_output_unit)
        self.cb_output_unit.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        if not self.cb_output_unit.get():
            self.cb_output_unit.set("Amp")

        # Coincidental Peaks
        ttk.Checkbutton(far_right, text="Coincidental Peaks", variable=self.var_coincidental)\
            .grid(row=2, column=0, sticky="w", padx=16, pady=8)

        # Multi Phase + dependent Average
        mp_frame = ttk.LabelFrame(far_right, text="Multi Phase")
        mp_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        ttk.Checkbutton(mp_frame, text="Multi Phase", variable=self.var_multi_phase,
                        command=self._toggle_multi_avg).grid(row=0, column=0, sticky="w", padx=6, pady=(6,2))
        self.chk_multi_avg = ttk.Checkbutton(mp_frame, text="Average", variable=self.var_multi_avg)
        self.chk_multi_avg.grid(row=1, column=0, sticky="w", padx=22, pady=(2,6))
        self._toggle_multi_avg()  # initialize disabled state

        # Bottom: Preview
        self.preview = tk.Text(self, height=6, wrap="word")
        self.preview.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(0,10))
        self.preview.configure(state="disabled")

        # Defaults for device combos
        for name, values in FIELDS:
            if values: self.current_values[name].set(values[0])
        if not self.cb_unit.get(): self.cb_unit.current(0)

    # ------------- Date helpers -------------
    def open_date_picker(self, var: tk.StringVar):
        try:
            current = parse_iso(var.get())
        except Exception:
            current = date.today()
        popup = DatePickerPopup(self, current, on_pick=lambda d: var.set(to_iso(d)))
        x = self.winfo_pointerx(); y = self.winfo_pointery()
        popup.geometry(f"+{x}+{y}")

    def apply_previous_range(self):
        label = self.var_prev_range.get()
        for lab, (s, e) in self.prev_ranges:
            if lab == label:
                self.var_start.set(s); self.var_end.set(e)
                self.var_date_preset.set("")
                return
        messagebox.showinfo("No range", "Select a previous range to apply.")

    def apply_date_preset(self):
        today = date.today()
        val = self.var_date_preset.get()
        if val == "yesterday":
            start = today - timedelta(days=1); end = today - timedelta(days=1)
        elif val in {"7", "30", "365"}:
            days = int(val); start = today - timedelta(days=days-1); end = today
        else:
            return
        self.var_start.set(to_iso(start)); self.var_end.set(to_iso(end))

    # ------------- Interval helpers -------------
    def apply_interval_preset(self):
        preset = self.var_interval_preset.get()
        if preset == "15m":
            self.var_interval_value.set("15"); self.var_interval_unit.set("minute")
        elif preset == "hourly":
            self.var_interval_value.set("1"); self.var_interval_unit.set("hour")
        elif preset == "daily":
            self.var_interval_value.set("24"); self.var_interval_unit.set("hour")
        elif preset == "weekly":
            self.var_interval_value.set("168"); self.var_interval_unit.set("hour")
        elif preset == "monthly":
            self.var_interval_value.set("720"); self.var_interval_unit.set("hour")

    # ------------- Shuttle logic -------------
    def add_selection(self, key: str):
        value = self.current_values[key].get().strip()
        if not value:
            messagebox.showinfo("No value selected", f"Please choose a value for '{key}' first.")
            return
        existing = self._find_item_by_key(key)
        if existing:
            self.tree.set(existing, "value", value)
        else:
            self.tree.insert("", "end", values=(key, value))

    def _find_item_by_key(self, key: str):
        for iid in self.tree.get_children(""):
            if self.tree.set(iid, "key") == key:
                return iid
        return None

    def remove_selected(self):
        for iid in self.tree.selection(): self.tree.delete(iid)

    def clear_all(self):
        for iid in self.tree.get_children(""): self.tree.delete(iid)

    def get_selected_params(self) -> dict:
        params = {}
        for iid in self.tree.get_children(""):
            k = self.tree.set(iid, "key"); v = self.tree.set(iid, "value")
            params[k] = v
        return params

    # ------------- Right column  -------------
    def _toggle_multi_avg(self):
        if self.var_multi_phase.get():
            self.chk_multi_avg.state(["!disabled"])
        else:
            self.var_multi_avg.set(False)
            self.chk_multi_avg.state(["disabled"])

    # ------------- Build query / preview -------------
    def build_rest_query(self):
        # ----- Validate dates -----
        try:
            start_d = parse_iso(self.var_start.get()); end_d = parse_iso(self.var_end.get())
        except Exception:
            messagebox.showerror("Invalid date", "Start/End dates must be YYYY-MM-DD.")
            return
        if start_d > end_d:
            messagebox.showerror("Invalid range", "Start Date must be on or before End Date.")
            return

        # ----- Devices converted to API keys -----
        device_params_gui = self.get_selected_params()
        api_key_map = {
            "Substation": "substation",
            "Line": "line",
            "Transformer": "transformer",
            "Bus": "bus",
            "Feeder": "feeder",
        }
        device_params = {api_key_map.get(k, k): v for k, v in device_params_gui.items()}

        # ----- Datasets list -----
        datasets = []
        if self.var_ds_min.get(): datasets.append("Minimum")
        if self.var_ds_avg.get(): datasets.append("Average")
        if self.var_ds_max.get(): datasets.append("Maximum")

        # ----- Build the APIParams dataclass -----
        params = api.build_api_params(
            device_params=device_params,
            start_date=self.var_start.get(),
            end_date=self.var_end.get(),
            interval_value=self.var_interval_value.get().strip(),
            interval_unit=(self.var_interval_unit.get().strip() or "minute"),
            datasets=datasets,
            output_unit=self.var_output_unit.get(),
            coincidental_peaks=self.var_coincidental.get(),
            multi_phase=self.var_multi_phase.get(),
            multi_phase_average=self.var_multi_avg.get(),
        )

        # ----- Compose URL for preview -----
        full_url = api.compose_url(self.api_config.base_url, params)
        preview_text = api.build_preview_text(params, full_url)
        self._set_preview(preview_text)

    # OPTIONAL: add a button to actually call the API
    def _wire_run_button(self, parent_frame):
        # You can call this from your UI builder to add a "Run" button near "Build REST Query"
        btn = ttk.Button(parent_frame, text="Run Query", command=self.run_query)
        btn.grid(row=0, column=3, sticky="ew", padx=4)

    def run_query(self):
        # Call the API and show a simple result dialog.
        # (Consider running this in a background thread for long calls)
        # Build params exactly as in build_rest_query, but without preview-only bits:
        try:
            start_d = parse_iso(self.var_start.get()); end_d = parse_iso(self.var_end.get())
        except Exception:
            messagebox.showerror("Invalid date", "Start/End dates must be YYYY-MM-DD.")
            return
        if start_d > end_d:
            messagebox.showerror("Invalid range", "Start Date must be on or before End Date.")
            return

        device_params_gui = self.get_selected_params()
        api_key_map = {"Substation":"substation","Line":"line","Transformer":"transformer","Bus":"bus","Feeder":"feeder"}
        device_params = {api_key_map.get(k, k): v for k, v in device_params_gui.items()}

        datasets = []
        if self.var_ds_min.get(): datasets.append("Minimum")
        if self.var_ds_avg.get(): datasets.append("Average")
        if self.var_ds_max.get(): datasets.append("Maximum")

        params = api.build_api_params(
            device_params=device_params,
            start_date=self.var_start.get(),
            end_date=self.var_end.get(),
            interval_value=self.var_interval_value.get().strip(),
            interval_unit=(self.var_interval_unit.get().strip() or "minute"),
            datasets=datasets,
            output_unit=self.var_output_unit.get(),
            coincidental_peaks=self.var_coincidental.get(),
            multi_phase=self.var_multi_phase.get(),
            multi_phase_average=self.var_multi_avg.get(),
        )

        status, text = api.execute_query(self.api_config, params)
        if status == 200:
            messagebox.showinfo("Success", "Request succeeded.\n\n(Preview)\n" + text[:1000])
        else:
            messagebox.showerror("Error", f"Status {status}\n{text[:1000]}")

    def _set_preview(self, text: str):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")


if __name__ == "__main__":
    app = DeviceShuttleApp()
    app.mainloop()
