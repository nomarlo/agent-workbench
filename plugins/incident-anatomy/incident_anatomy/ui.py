"""The viewer's own words. An anatomy file overrides any of them with "ui"."""

STRINGS = {
    "en": {
        "simulation_title": "The mechanism, step by step",
        "simulation_lede": "Step through one {iteration} and watch the three panels: what the code does, what stays retained, and the exact line that does it. Turn the fixes on to see which path disappears.",
        "prev": "←",
        "next": "Next step →",
        "complete": "Complete the {iteration}",
        "reset": "Reset",
        "step": "step",
        "real_time": "≈ {time} real time",
        "keyboard": "Keyboard: ← → to step back and forth.",
        "flow": "Flow of the {iteration}",
        "no_fixes": "no fixes",
        "state": "Retained state",
        "code_hint": "highlighted: what this step runs",
        "code_elsewhere": "this step runs another file (marked •)",
        "none": "None",
        "empty": "Nothing retained yet.",
        "empty_fixed": "Nothing retained across iterations.",
        "more": "… {n} more",
        "idle": "Nothing retained yet.",
        "growing": "{n} × {iteration} retained · {value} {unit}",
        "limit": "Limit reached.",
        "flat": "Flat: nothing survives the end of the {iteration}.",
        "fix": "Fix {i}",
        "where": "Where:",
        "sources": "Sources",
        "generated": "Code excerpts are read from git at {sha} ({subject}) by incident-anatomy, and every fix is a patch that applies cleanly to that commit. Charts and data tables are drawn from the data files named in their captions.",
        "partial": "dashed: partial data",
        "iteration": "iteration",
    },
    "es": {
        "simulation_title": "El mecanismo, paso a paso",
        "simulation_lede": "Avanza paso a paso por un {iteration} y mira los tres paneles: qué hace el código, qué queda retenido y la línea exacta que lo hace. Activa los fixes para ver qué camino desaparece.",
        "prev": "←",
        "next": "Siguiente paso →",
        "complete": "Completar {iteration}",
        "reset": "Reiniciar",
        "step": "paso",
        "real_time": "≈ {time} reales",
        "keyboard": "Teclado: ← → para avanzar y retroceder.",
        "flow": "Flujo del {iteration}",
        "no_fixes": "sin fixes",
        "state": "Estado retenido",
        "code_hint": "resaltado: lo que ejecuta este paso",
        "code_elsewhere": "este paso ejecuta otro archivo (marcado con •)",
        "none": "None",
        "empty": "Todavía nada retenido.",
        "empty_fixed": "Nada retenido entre iteraciones.",
        "more": "… {n} más",
        "idle": "Todavía nada retenido.",
        "growing": "{n} × {iteration} retenidos · {value} {unit}",
        "limit": "Límite alcanzado.",
        "flat": "Plano: nada sobrevive al final del {iteration}.",
        "fix": "Fix {i}",
        "where": "Dónde:",
        "sources": "Fuentes",
        "generated": "Los extractos de código los lee incident-anatomy de git en {sha} ({subject}), y cada fix es un patch que aplica limpio sobre ese commit. Las gráficas y tablas de datos salen de los archivos nombrados en sus pies.",
        "partial": "rayado: datos parciales",
        "iteration": "iteración",
    },
}


def strings(lang: str, overrides: dict[str, str]) -> dict[str, str]:
    unknown = sorted(set(overrides) - set(STRINGS["en"]))
    if unknown:
        from incident_anatomy.errors import AnatomyError

        raise AnatomyError(f"ui: unknown key(s) {', '.join(unknown)} (known: {', '.join(sorted(STRINGS['en']))})")
    return {**STRINGS[lang], **overrides}
