import os
import json
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

IMAGE_PATH = os.path.join("image", "EG_crop_new.png")
OUTPUT_JSON = "graph_EG.json"

SNAP_ENABLED = True
SNAP_TOLERANCE = 15  # Pixel Toleranz


def compute_snap(x, y, nodes):
    """
    Berechnet einen möglichen Snap auf vorhandene x-/y-Koordinaten.

    Gibt zurück:
    (snapped_x, snapped_y, snapped_to_x, snapped_to_y)
    """
    if not SNAP_ENABLED or not nodes:
        return float(x), float(y), False, False

    snapped_x = x
    snapped_y = y
    snapped_to_x = False
    snapped_to_y = False

    # Horizontal: gleiche y
    for n in nodes:
        if abs(n["y"] - y) < SNAP_TOLERANCE:
            snapped_y = n["y"]
            snapped_to_y = True
            break

    # Vertikal: gleiche x
    for n in nodes:
        if abs(n["x"] - x) < SNAP_TOLERANCE:
            snapped_x = n["x"]
            snapped_to_x = True
            break

    return float(snapped_x), float(snapped_y), snapped_to_x, snapped_to_y


def pick_nodes(image_path):
    """Zeigt das Bild und lässt dich Nodes setzen (mit Axis-Snapping & visueller Snap-Linie)."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Bild nicht gefunden: {image_path}")

    img = mpimg.imread(image_path)

    fig, ax = plt.subplots()
    ax.imshow(img)
    ax.set_title(
        "Left-click: add node (auto-snap to axis)\n"
        "Right-click: finish nodes\n"
        "Beweg die Maus, um Snap-Linien zu sehen"
    )
    plt.axis("off")

    nodes = []

    # Artists für Snap-Linien (anfangs None)
    hline_artist = None
    vline_artist = None

    # --- Mouse-Move-Handler: zeigt Snap-Linien an ---
    def on_move(event):
        nonlocal hline_artist, vline_artist

        if event.inaxes != ax or not SNAP_ENABLED:
            # Falls außerhalb der Achse: Linien ausblenden
            changed = False
            if hline_artist is not None and hline_artist.get_visible():
                hline_artist.set_visible(False)
                changed = True
            if vline_artist is not None and vline_artist.get_visible():
                vline_artist.set_visible(False)
                changed = True
            if changed:
                fig.canvas.draw_idle()
            return

        x, y = event.xdata, event.ydata
        snapped_x, snapped_y, snapped_to_x, snapped_to_y = compute_snap(x, y, nodes)

        # Achsenbereiche holen
        x_min, x_max = ax.get_xlim()
        y_min, y_max = ax.get_ylim()

        changed = False

        # Horizontale Linie (Snap auf y)
        if snapped_to_y:
            if hline_artist is None:
                hline_artist = ax.axhline(
                    snapped_y,
                    linestyle="--",
                    linewidth=1,
                    color="black",
                    alpha=0.6,
                )
            else:
                hline_artist.set_ydata([snapped_y, snapped_y])
                hline_artist.set_visible(True)
            changed = True
        else:
            if hline_artist is not None and hline_artist.get_visible():
                hline_artist.set_visible(False)
                changed = True

        # Vertikale Linie (Snap auf x)
        if snapped_to_x:
            if vline_artist is None:
                vline_artist = ax.axvline(
                    snapped_x,
                    linestyle="--",
                    linewidth=1,
                    color="black",
                    alpha=0.6,
                )
            else:
                vline_artist.set_xdata([snapped_x, snapped_x])
                vline_artist.set_visible(True)
            changed = True
        else:
            if vline_artist is not None and vline_artist.get_visible():
                vline_artist.set_visible(False)
                changed = True

        if changed:
            fig.canvas.draw_idle()

    # --- Click-Handler: setzt Node (mit Snap) ---
    def onclick(event):
        if event.inaxes != ax:
            return

        if event.button == 1:  # left click → Node hinzufügen
            x, y = event.xdata, event.ydata
            x, y, _, _ = compute_snap(x, y, nodes)

            node_id = len(nodes)
            nodes.append({
                "id": node_id,
                "x": float(x),
                "y": float(y)
            })

            ax.plot(x, y, "ro")
            ax.text(x + 5, y + 5, str(node_id), color="red", fontsize=9)
            fig.canvas.draw_idle()

        elif event.button == 3:  # right click → fertig
            fig.canvas.mpl_disconnect(cid_click)
            fig.canvas.mpl_disconnect(cid_move)
            plt.close(fig)

    cid_click = fig.canvas.mpl_connect("button_press_event", onclick)
    cid_move = fig.canvas.mpl_connect("motion_notify_event", on_move)

    plt.show()
    return nodes


def classify_nodes(nodes):
    print("\nNodes klassifizieren:")
    print("Gib für jeden Node den Typ ein: 'd' = door, 'j' = junction (default: j)\n")

    for n in nodes:
        print(f"Node {n['id']} bei (x={n['x']:.1f}, y={n['y']:.1f})")
        t = input("  Typ [d=door / j=junction]: ").strip().lower()

        if t == "d":
            n["type"] = "door"
            room = input("  room_id (z.B. H-2.14, Enter für leer): ").strip()
            if room:
                n["room_id"] = room
        else:
            n["type"] = "junction"

    return nodes


def pick_edges(nodes):
    if not nodes:
        print("Keine Nodes vorhanden, es werden keine Edges erzeugt.")
        return []

    node_by_id = {n["id"]: n for n in nodes}

    print("\nNodes (Knoten):")
    for n in nodes:
        info = f"id={n['id']} | {n.get('type','?')} | x={n['x']:.1f}, y={n['y']:.1f}"
        if n.get("room_id"):
            info += f" | room_id={n['room_id']}"
        print("  " + info)

    print("\nJetzt Kanten definieren (nur gerade Linien).")
    print("Gib jeweils zwei Node-IDs ein, z.B.: 0 1")
    print("Leere Eingabe = fertig.\n")

    edges = []
    edge_id = 0
    node_ids = set(node_by_id.keys())

    while True:
        line = input(f"Edge #{edge_id} (from_id to_id): ").strip()
        if not line:
            break

        parts = line.split()
        if len(parts) != 2:
            print("➡ Bitte genau zwei IDs eingeben, z.B. '0 1'.")
            continue

        try:
            from_id = int(parts[0])
            to_id = int(parts[1])
        except ValueError:
            print("➡ IDs müssen ganze Zahlen sein.")
            continue

        if from_id not in node_ids or to_id not in node_ids:
            print("➡ Eine der IDs existiert nicht.")
            continue

        edges.append({
            "id": edge_id,
            "from": from_id,
            "to": to_id
        })

        edge_id += 1

    return edges


def main():
    print(f"Bild wird geladen: {IMAGE_PATH}")
    nodes = pick_nodes(IMAGE_PATH)
    print(f"\n{len(nodes)} Nodes gesetzt.")

    nodes = classify_nodes(nodes)
    edges = pick_edges(nodes)
    print(f"\n{len(edges)} Edges definiert.")

    graph = {
        "image": IMAGE_PATH,
        "nodes": nodes,
        "edges": edges
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    print(f"\n Graph in '{OUTPUT_JSON}' gespeichert.")
    print("Fertig.")


if __name__ == "__main__":
    main()
