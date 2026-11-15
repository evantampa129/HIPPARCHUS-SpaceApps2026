"""The scenes, in order, with what each one is allowed to call itself."""

SCENES = [
    # (module, class); labels and evidence files live in each scene module
    ("m01_ancient_sky", "M01AncientSky"),
    ("m02_filters", "M02Filters"),
    ("m03_aperture", "M03Aperture"),
    ("m04_epsf", "M04EPSF"),
    ("m05_fingerprint", "M05Fingerprint"),
    ("m06_kleopatra", "M06Kleopatra"),
    ("m07_shift_stack", "M07ShiftStack"),
    ("m08_falsification", "M08Falsification"),
    ("m09_compat_graph", "M09CompatGraph"),
    ("m10_spectral_time", "M10SpectralTime"),
    ("m11_change_real", "M11ChangeReal"),
    ("m12_wcs", "M12WCS"),
    ("m13_uncertainty", "M13Uncertainty"),
    ("m14_barnard_refusal", "M14BarnardRefusal"),
    ("m15_identity", "M15Identity"),
]
