"""Version-specific addresses found by reverse engineering (see docs/RE-NOTES.md).

Add a new firmware version by re-running scripts/ghidra_analyze.ps1 -Version vX.Y,
finding the same spots, and adding an entry keyed by the image's sha256.
"""

KNOBS = ("shape", "cluster", "color", "orbits", "space", "effects")

V3_6 = {
    "text_segment": 2,                 # index of .flash.text in the app image (code cave goes after it)

    # ---- parameter mixing routine (FUN_400e2bf4): knob + CV (+ SPACE scaling) -> engine
    "param_mix": 0x400E2BF4,
    "y_load": (0x400E3118, "130611"),  # lsi f1, a6, 0x44   ; f1 = settings.tabla (Y row)
                                       #  dead here: a8, f0, f2, f3, b0
    # knob + CV adds: (addr, original bytes, asm that keeps the knob but drops the CV)
    "cv_add": {
        "shape":   (0x400E2D4D, "50660a", "    mov.s   f6, f6"),
        "cluster": (0x400E2D5F, "40550a", "    mov.s   f5, f5"),
        "color":   (0x400E2D6E, "30a40a", "    mov.s   f10, f4"),
        "space":   (0x400E2D74, "00010a", "    mov.s   f0, f1"),
        "orbits":  (0x400E2D7D, "20930a", "    mov.s   f9, f3"),
        "effects": (0x400E2D88, "10820a", "    mov.s   f8, f2"),
    },

    # ---- RAM globals (float unless noted)
    "space_amounts": 0x3FFC35D0,       # SPACE-menu amounts val_1..val_7: FREQ, ORBITS, COLOR, SHAPE, SPACE!, EFFECTS, CLUSTER
    "settings": 0x3FFC80C0,           # +0x44 tabla, +0x48 acorde, +0x4c cant_esp(volume), +0x50 octava ...
    "cv": {                            # normalised CV input values written by the ADC task
        "shape": 0x3FFC357C, "cluster": 0x3FFC3580, "color": 0x3FFC358C,
        "orbits": 0x3FFC3578, "space": 0x3FFC3584, "effects": 0x3FFC3588,
        "exciter": 0x3FFC3574,
    },
    "knob": {                          # knob values (normal mode)
        "freq": 0x3FFC8114, "cluster": 0x3FFC80C4, "color": 0x3FFC80C8, "shape": 0x3FFC80CC,
        "orbits": 0x3FFC80D0, "space": 0x3FFC80D4, "effects": 0x3FFC80D8,
    },
    "secondary": {                     # ORBITS-menu values (NVS-backed)
        "decay": 0x3FFC80F8, "lpg_color": 0x3FFC80FC, "tabla": 0x3FFC8104, "acorde": 0x3FFC8108,
        "volume": 0x3FFC810C, "octava": 0x3FFC8110, "modores": 0x3FFC8134,
    },
    "wavetable_ram": 0x3FFC40C0,       # int16[64][128]

    # ---- flash data
    "chord_table": 0x3F40EC34,         # float[16][8] voice frequency ratios

    # ---- wavetable storage (NVS namespace "storage", keys "onda_0".."onda_7" = rows of 8 waves)
    "wave_key_fmt": 0x3F404674,        # "onda_%d"
    "wave_key_loads": [(0x400E4355, "a12"),   # load slot  (FUN_400e4338)
                       (0x400E4B4D, "a12"),   # save slot  (FUN_400e4b2c, used by MAGW upload)
                       (0x400E4CB8, "a5")],   # erase all  (FUN_400e4ca0, MAGD)
    "factory_waves": 0x3F4119FC,       # int32[8 rows][1024] = 64 waves x 128 samples (low 16 bits used)
    "wave_loader": 0x400E4BC0,         # load 8 rows into RAM; missing rows <- factory table (int32[8][1024] @0x3f4119fc)
    "wave_boot_load_call": 0x400E4C9B, # call8 wave_loader in nvs_inicio (runs BEFORE settings are loaded)
    "space_load": 0x400E4AB4,          # load SPACE amounts (defaults first) - called at boot
    "space_load_calls": [0x400E1D22, 0x400E1D70],
    "space_save": 0x400E4A00,          # save SPACE amounts - called when leaving the SPACE menu
    "space_save_calls": [0x400E3A96],
    "space_default_stores": (0x400E4AC6, 0x400E4AD5),   # 7x s32i a8 (=0.75), a2 = space_amounts
    "effects_space_msub": 0x400E2DEF,  # msub.s f1, f13, f8 : EFFECTS -= SPACE amount * EFFECTS
    "unused_rodata": (0x3F4080C8, 64, b"ESP_ERR_WIFI_TWT_SETUP_TIMEOUT"),  # WiFi error names: never printed

    # ---- ESP-IDF logging (initialised .data): esp_log default level, 3 = INFO
    "log_level": (0x3FFB0054, "03000000"),
}

BY_SHA256 = {
    "64f8ee24f19ee6085594ccb9a6d7697e7f90b7d325b4615a65651ff8a452e328": ("3.6", V3_6),
}
