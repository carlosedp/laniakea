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

    # ---- LED ring (task FUN_400e12c8)
    "menu_state": 0x3FFC40B4,          # 0 normal, 1 SPACE menu, 2 ORBITS menu (others: calibration)
    "led_value_store": 0x400E1666,     # ssi f1, a7, 136 : dot target = 1 + knob*6 ; a3 = knob id code
    "led_knob_id_effects": 0xC0,       # a3 for EFFECTS (unique in the SPACE menu)

    # ---- UART command task (FUN_400e05fc): "MAG" + 'W' (upload) / 'D' (factory); a4 = 4th char
    "uart_cmd_d_check": 0x400E0825,    # movi a8, 'D'  (then bne a4, a8, reset)
    "uart_cmd_done": 0x400E0820,       # common tail: prefix counter = 0, continue loop
    "uart_write_bytes": 0x400D76A0,    # uart_write_bytes(port, buf, len)
    "wave_erase": 0x400E4CA0,          # erase the 8 rows (MAGD); does NOT reload RAM
    "uart_magd_erase_call": 0x400E071B,

    # ---- constants loaded from shared literal pools (usability patch redirects the loads)
    "y_scale_load": (0x400DD1FF, "a8"),     # l32r a8, =9.0  (voice renderer: row = Y * 9)
    "freq_span_load": (0x400E2F2B, "a10"),  # l32r a10, =7.0 (mixer: (oct-1)*12 + FREQ*7 + 12)

    # ---- pitch (quantizer patch)
    "pitch_sum": 0x400E2F7C,           # add.s f0, f2, f3  ; f0 = total pitch (V/OCT + FREQ note)
    "freq_space_msub": 0x400E2F57,     # msub.s f3, f2, f1 ; note -= SPACE amount * note

    # ---- LED strip driver wrappers (led_dedupe patch); both start with `entry a1, 48`
    "led_set_pixel_fn": 0x400E58A8,
    "led_refresh_fn": 0x400E58E0,

    # ---- ESP-IDF logging (initialised .data): esp_log default level, 3 = INFO
    "log_level": (0x3FFB0054, "03000000"),
}

V3_7 = {   # ported from 3.6 by re/port_syms.py, checked by hand (docs/RE-NOTES.md)
    "text_segment": 2,                 # index of .flash.text in the app image (code cave goes after it)

    # ---- parameter mixing routine (FUN_400e2bf4): knob + CV (+ SPACE scaling) -> engine
    "param_mix": 0x400E33D4,
    "y_load": (0x400E38F8, "130611"),  # lsi f1, a6, 0x44   ; f1 = settings.tabla (Y row)
                                       #  dead here: a8, f0, f2, f3, b0
    # knob + CV adds: (addr, original bytes, asm that keeps the knob but drops the CV)
    "cv_add": {
        "shape":   (0x400E352D, "50660a", "    mov.s   f6, f6"),
        "cluster": (0x400E353F, "40550a", "    mov.s   f5, f5"),
        "color":   (0x400E354E, "30a40a", "    mov.s   f10, f4"),
        "space":   (0x400E3554, "00010a", "    mov.s   f0, f1"),
        "orbits":  (0x400E355D, "20930a", "    mov.s   f9, f3"),
        "effects": (0x400E3568, "10820a", "    mov.s   f8, f2"),
    },

    # ---- RAM globals (float unless noted)
    "space_amounts": 0x3FFC6228,       # SPACE-menu amounts val_1..val_7: FREQ, ORBITS, COLOR, SHAPE, SPACE!, EFFECTS, CLUSTER
    "settings": 0x3FFCAD18,           # +0x44 tabla, +0x48 acorde, +0x4c cant_esp(volume), +0x50 octava ...
    "cv": {                            # normalised CV input values written by the ADC task
        "shape": 0x3FFC61D4, "cluster": 0x3FFC61D8, "color": 0x3FFC61E4,
        "orbits": 0x3FFC61D0, "space": 0x3FFC61DC, "effects": 0x3FFC61E0,
        "exciter": 0x3FFC61CC,
    },
    "knob": {                          # knob values (normal mode)
        "freq": 0x3FFCAD6C, "cluster": 0x3FFCAD1C, "color": 0x3FFCAD20, "shape": 0x3FFCAD24,
        "orbits": 0x3FFCAD28, "space": 0x3FFCAD2C, "effects": 0x3FFCAD30,
    },
    "secondary": {                     # ORBITS-menu values (NVS-backed)
        "decay": 0x3FFCAD50, "lpg_color": 0x3FFCAD54, "tabla": 0x3FFCAD5C, "acorde": 0x3FFCAD60,
        "volume": 0x3FFCAD64, "octava": 0x3FFCAD68, "modores": 0x3FFCAD8C,
    },
    "wavetable_ram": 0x3FFC6D18,       # int16[64][128]

    # ---- flash data
    "chord_table": 0x3F40EC34,         # float[16][8] voice frequency ratios

    # ---- wavetable storage (NVS namespace "storage", keys "onda_0".."onda_7" = rows of 8 waves)
    "wave_key_fmt": 0x3F404674,        # "onda_%d"
    "wave_key_loads": [(0x400E4B2D, "a12"),   # load slot  (FUN_400e4338)
                       (0x400E5325, "a12"),   # save slot  (FUN_400e4b2c, used by MAGW upload)
                       (0x400E5490, "a5")],   # erase all  (FUN_400e4ca0, MAGD)
    "factory_waves": 0x3F4119FC,       # int32[8 rows][1024] = 64 waves x 128 samples (low 16 bits used)
    "wave_loader": 0x400E5398,         # load 8 rows into RAM; missing rows <- factory table (int32[8][1024] @0x3f4119fc)
    "wave_boot_load_call": 0x400E5473, # call8 wave_loader in nvs_inicio (runs BEFORE settings are loaded)
    "space_load": 0x400E528C,          # load SPACE amounts (defaults first) - called at boot
    "space_load_calls": [0x400E24F6, 0x400E2544],
    "space_save": 0x400E51D8,          # save SPACE amounts - called when leaving the SPACE menu
    "space_save_calls": [0x400E426E],
    "space_default_stores": (0x400E529E, 0x400E52AD),   # 7x s32i a8 (=0.75), a2 = space_amounts
    "effects_space_msub": 0x400E35CF,  # msub.s f1, f13, f8 : EFFECTS -= SPACE amount * EFFECTS
    "unused_rodata": (0x3F4080C8, 64, b"ESP_ERR_WIFI_TWT_SETUP_TIMEOUT"),  # WiFi error names: never printed

    # ---- LED ring (task FUN_400e12c8)
    "menu_state": 0x3FFC6D0C,          # 0 normal, 1 SPACE menu, 2 ORBITS menu (others: calibration)
    "led_value_store": 0x400E1E3A,     # ssi f1, a7, 136 : dot target = 1 + knob*6 ; a3 = knob id code
    "led_knob_id_effects": 0xC0,       # a3 for EFFECTS (unique in the SPACE menu)

    # ---- UART command task (FUN_400e05fc): "MAG" + 'W' (upload) / 'D' (factory); a4 = 4th char
    "uart_cmd_d_check": 0x400E0FF9,    # movi a8, 'D'  (then bne a4, a8, reset)
    "uart_cmd_done": 0x400E0FF4,       # common tail: prefix counter = 0, continue loop
    "uart_write_bytes": 0x400D776C,    # uart_write_bytes(port, buf, len)
    "wave_erase": 0x400E5478,          # erase the 8 rows (MAGD); does NOT reload RAM
    "uart_magd_erase_call": 0x400E0EEF,

    # ---- constants loaded from shared literal pools (usability patch redirects the loads)
    "y_scale_load": (0x400DD4B3, "a8"),     # l32r a8, =9.0  (voice renderer: row = Y * 9)
    "freq_span_load": (0x400E370B, "a10"),  # l32r a10, =7.0 (mixer: (oct-1)*12 + FREQ*7 + 12)

    # ---- pitch (quantizer patch)
    "pitch_sum": 0x400E375C,           # add.s f0, f2, f3  ; f0 = total pitch (V/OCT + FREQ note)
    "freq_space_msub": 0x400E3737,     # msub.s f3, f2, f1 ; note -= SPACE amount * note

    # ---- LED strip driver wrappers (led_dedupe patch); both start with `entry a1, 48`
    "led_set_pixel_fn": 0x400E6080,
    "led_refresh_fn": 0x400E60B8,

    # ---- ESP-IDF logging (initialised .data): esp_log default level, 3 = INFO
    "log_level": (0x3FFB0054, "03000000"),
}

BY_SHA256 = {
    "64f8ee24f19ee6085594ccb9a6d7697e7f90b7d325b4615a65651ff8a452e328": ("3.6", V3_6),
    "936f9fd502e5e350cc23982bee64c8b6cfeb5dbd3efcbf4dd76fca5585de1b2d": ("3.7", V3_7),
}
