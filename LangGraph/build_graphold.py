import os
import json
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

IMAGE_PATH = os.path.join("image", "floorplan.png")
OUTPUT_JSON = "graph.json"


def pick_nodes(image_path):
    """Zeigt das Bild und lässt dich per Mausklick Nodes setzen (erstmal ohne Typ)."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Bild nicht gefunden: {image_path}")

    img = mpimg.imread(image_path)

    fig, ax = plt.subplots()
    ax.imshow(img)
    ax.set_title("Left-click: add node   |   Right-click: finish nodes")
    plt.axis("off")

    nodes = []

    def onclick(event):
        if event.inaxes != ax:
            return

        if event.button == 1:  # left click
            x, y = event.xdata, event.ydata
            node_id = len(nodes)
            # Typ & room_id kommen später
            nodes.append({
                "id": node_id,
                "x": float(x),
                "y": float(y)
            })

            ax.plot(x, y, "ro")
            ax.text(x + 5, y + 5, str(node_id), color="red", fontsize=9)
            fig.canvas.draw_idle()

        elif event.button == 3:  # right click = fertig
            fig.canvas.mpl_disconnect(cid)
            plt.close(fig)

    cid = fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()

    return nodes


def classify_nodes(nodes):
    """Fragt für jeden Node ab, ob door oder junction (und optional room_id)."""
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
    """Fragt im Terminal, welche Nodes durch Kanten verbunden sind."""
    if not nodes:
        print("Keine Nodes vorhanden, es werden keine Edges erzeugt.")
        return []

    print("\nNodes (Knoten):")
    for n in nodes:
        info = f"id={n['id']}, type={n.get('type','?')}, x={n['x']:.1f}, y={n['y']:.1f}"
        if n.get("room_id"):
            info += f", room_id={n['room_id']}"
        print("  " + info)

    print("\nJetzt Kanten definieren.")
    print("Gib jeweils zwei Node-IDs ein, z.B.: 0 1")
    print("Leere Eingabe = fertig.\n")

    edges = []
    edge_id = 0
    node_ids = {n["id"] for n in nodes}

    while True:
        line = input(f"Edge #{edge_id} (from_id to_id, Enter zum Beenden): ").strip()
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
            print("➡ Eine der IDs existiert nicht, bitte gültige Node-IDs verwenden.")
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

    print(f"\n✅ Graph in '{OUTPUT_JSON}' gespeichert.")
    print("Fertig.")


if __name__ == "__main__":
    main()
