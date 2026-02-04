"""
Navigation module for pathfinding on floor plans.
Uses Dijkstra's algorithm to find shortest paths between nodes.
Supports multiple floors: EG (ground), 1OG (1st floor), 2OG (2nd floor).
"""

import json
import heapq
import math
import re
from pathlib import Path
from typing import Optional, Tuple

# Base path for graph files
BASE_PATH = Path(__file__).resolve().parent.parent.parent.parent

# Graph files for each floor (in graphs/ subdirectory)
GRAPH_FILES = {
    'EG': BASE_PATH / "graphs" / "graph_EG.json",
    '1OG': BASE_PATH / "graphs" / "graph_1OG.json",
    '2OG': BASE_PATH / "graphs" / "graph_2OG.json",
}

# Floor plan images
FLOOR_IMAGES = {
    'EG': 'floorplans/EG.png',
    '1OG': 'floorplans/1OG.png',
    '2OG': 'floorplans/2OG.png',
}

# Cache for graph data (per floor)
_graph_cache = {}

# Cache for navigable rooms (per floor)
_navigable_rooms_cache = {}


def get_floor_for_room(room_id: str) -> Optional[str]:
    """
    Determine which floor a room is on based on room number.
    - EG (ground floor): 1-2 digit numbers (1-99)
    - 1OG (1st floor): 3-digit numbers starting with 1 (100-199)
    - 2OG (2nd floor): 3-digit numbers starting with 2 (200-299)
    """
    if not room_id or not room_id.isdigit():
        return None
    
    room_num = int(room_id)
    
    if room_num < 100:
        return 'EG'
    elif 100 <= room_num < 200:
        return '1OG'
    elif 200 <= room_num < 300:
        return '2OG'
    
    return None


def load_graph(floor: str) -> Optional[dict]:
    """Load and cache the navigation graph for a specific floor."""
    if floor not in GRAPH_FILES:
        return None
    
    if floor not in _graph_cache:
        graph_path = GRAPH_FILES[floor]
        if not graph_path.exists():
            return None
        with open(graph_path, 'r', encoding='utf-8') as f:
            _graph_cache[floor] = json.load(f)
    
    return _graph_cache[floor]


def get_navigable_rooms_for_floor(floor: str) -> set:
    """Get all navigable room IDs for a specific floor."""
    if floor not in _navigable_rooms_cache:
        graph = load_graph(floor)
        if graph is None:
            return set()
        
        rooms = set()
        for node in graph['nodes']:
            if node.get('type') == 'door' and node.get('room_id'):
                rooms.add(node['room_id'])
        _navigable_rooms_cache[floor] = rooms
    
    return _navigable_rooms_cache[floor]


def get_navigable_rooms() -> set:
    """Get all navigable room IDs from all floors."""
    all_rooms = set()
    for floor in GRAPH_FILES.keys():
        all_rooms.update(get_navigable_rooms_for_floor(floor))
    return all_rooms


def get_node_by_id(graph: dict, node_id: int) -> Optional[dict]:
    """Get a node by its ID."""
    for node in graph['nodes']:
        if node['id'] == node_id:
            return node
    return None


def get_door_node_by_room(graph: dict, room_id: str) -> Optional[dict]:
    """Find the door node for a specific room."""
    for node in graph['nodes']:
        if node.get('type') == 'door' and node.get('room_id') == room_id:
            return node
    return None


def build_adjacency_list(graph: dict) -> dict:
    """Build an adjacency list from edges with distances as weights."""
    adjacency = {}
    nodes = {node['id']: node for node in graph['nodes']}
    
    for edge in graph['edges']:
        from_id = edge['from']
        to_id = edge['to']
        
        # Calculate Euclidean distance as weight
        from_node = nodes[from_id]
        to_node = nodes[to_id]
        distance = math.sqrt(
            (to_node['x'] - from_node['x']) ** 2 + 
            (to_node['y'] - from_node['y']) ** 2
        )
        
        # Bidirectional edges
        if from_id not in adjacency:
            adjacency[from_id] = []
        if to_id not in adjacency:
            adjacency[to_id] = []
            
        adjacency[from_id].append((to_id, distance))
        adjacency[to_id].append((from_id, distance))
    
    return adjacency


def dijkstra(adjacency: dict, start: int, end: int) -> Optional[list]:
    """
    Find shortest path from start to end using Dijkstra's algorithm.
    Returns list of node IDs representing the path, or None if no path exists.
    """
    # Priority queue: (distance, node_id, path)
    heap = [(0, start, [start])]
    visited = set()
    
    while heap:
        dist, current, path = heapq.heappop(heap)
        
        if current in visited:
            continue
            
        visited.add(current)
        
        if current == end:
            return path
        
        for neighbor, weight in adjacency.get(current, []):
            if neighbor not in visited:
                new_dist = dist + weight
                new_path = path + [neighbor]
                heapq.heappush(heap, (new_dist, neighbor, new_path))
    
    return None


def get_route_to_room(room_id: str, start_node_id: int = 0) -> Optional[dict]:
    """
    Get the route from start node to a specific room.
    
    Args:
        room_id: The room number (e.g., "245", "15", "131")
        start_node_id: The starting node ID (default: 0, the entrance/stairs)
    
    Returns:
        Dictionary with route information:
        - path: List of node IDs
        - coordinates: List of (x, y) coordinate pairs for drawing
        - target_room: The room ID
        - door_node: The door node coordinates
        - image: Path to the floor plan image
        - floor: The floor identifier
    """
    # Determine which floor this room is on
    floor = get_floor_for_room(room_id)
    if floor is None:
        return None
    
    # Check if room is navigable on this floor
    if room_id not in get_navigable_rooms_for_floor(floor):
        return None
    
    graph = load_graph(floor)
    if graph is None:
        return None
    
    # Find the door node for this room
    door_node = get_door_node_by_room(graph, room_id)
    if door_node is None:
        return None
    
    # Build adjacency list and find path
    adjacency = build_adjacency_list(graph)
    path = dijkstra(adjacency, start_node_id, door_node['id'])
    
    if path is None:
        return None
    
    # Convert path to coordinates
    nodes = {node['id']: node for node in graph['nodes']}
    coordinates = [(nodes[node_id]['x'], nodes[node_id]['y']) for node_id in path]
    
    return {
        'path': path,
        'coordinates': coordinates,
        'target_room': room_id,
        'door_node': {
            'x': door_node['x'],
            'y': door_node['y'],
            'id': door_node['id']
        },
        'image': FLOOR_IMAGES[floor],
        'floor': floor
    }


def extract_room_from_text(text: str) -> Optional[str]:
    """
    Extract a navigable room number from text.
    Returns the first matching room number found.
    """
    navigable = get_navigable_rooms()
    
    # Look for room numbers in the text
    # Match patterns like "room 245", "Raum 245", "245", etc.
    patterns = [
        r'(?:room|raum|zimmer|büro|office)\s*(\d{1,3})',  # "room 245" or "room 15"
        r'\b([12]\d{2})\b',  # 3-digit numbers starting with 1 or 2 (1OG/2OG)
        r'\b(\d{1,2})\b',  # 1-2 digit numbers (EG)
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            room = match if isinstance(match, str) else match[0]
            if room in navigable:
                return room
    
    return None


def is_navigable_room(room_id: str) -> bool:
    """Check if a room supports navigation."""
    return room_id in get_navigable_rooms()


# Test function
if __name__ == "__main__":
    # Test the pathfinding
    result = get_route_to_room("245")
    if result:
        print(f"Route to room 245:")
        print(f"  Path: {result['path']}")
        print(f"  Coordinates: {result['coordinates']}")
        print(f"  Door at: ({result['door_node']['x']}, {result['door_node']['y']})")
    else:
        print("No route found")
