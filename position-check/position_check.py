import os
import math
import requests
import polyline
from shapely.geometry import Point, LineString
from pyproj import Transformer
from dotenv import load_dotenv

load_dotenv()

class RouteChecker:
    def __init__(self, start: tuple[float, float], destination: tuple[float, float], api_key: str = None):
        self.start = start
        self.destination = destination
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        self.off_route_threshold_meters = 35.0
        
        # Metric projection centered on destination
        self.transformer = Transformer.from_crs(
            "EPSG:4326",
            f"+proj=aeqd +lat_0={self.destination[0]} +lon_0={self.destination[1]} +datum=WGS84 +units=m",
            always_xy=True
        )
        
        self.route_line = None
        self.last_dist = None
        
        self._initialize_route()

    def _initialize_route(self):
        coords = self._fetch_route()
        metric_points = [self.transformer.transform(lon, lat) for lat, lon in coords]
        self.route_line = LineString(metric_points)

    def _fetch_route(self):
        print("Fetching walking route from Google Maps (Routes API)...")
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "routes.polyline.encodedPolyline"
        }
        body = {
            "origin": {"location": {"latLng": {"latitude": self.start[0], "longitude": self.start[1]}}},
            "destination": {"location": {"latLng": {"latitude": self.destination[0], "longitude": self.destination[1]}}},
            "travelMode": "WALK"
        }
        res = requests.post(url, json=body, headers=headers).json()
        if "routes" not in res or not res["routes"]:
            raise ValueError(f"Routes API Error: {res}")
        
        encoded = res["routes"][0]["polyline"]["encodedPolyline"]
        decoded = polyline.decode(encoded)
        print(f"Route loaded with {len(decoded)} waypoints.")
        return decoded

    @staticmethod
    def get_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000  # Earth radius in meters
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def check_position(self, current_lat: float, current_lon: float) -> dict:
        if self.route_line is None:
            raise RuntimeError("Route not ready")

        # 1. On/Off route check
        px, py = self.transformer.transform(current_lon, current_lat)
        cross_track_meters = Point(px, py).distance(self.route_line)
        on_route = cross_track_meters <= self.off_route_threshold_meters

        # 2. Distance progress check
        current_dist = self.get_distance_meters(current_lat, current_lon, self.destination[0], self.destination[1])
        getting_closer = False
        if self.last_dist is not None:
            getting_closer = (current_dist - self.last_dist) < -1.5
        self.last_dist = current_dist

        print(f"ON_ROUTE: {str(on_route):<5} | GETTING_CLOSER: {str(getting_closer):<5} | Dist: {int(current_dist)}m (Drift: {int(cross_track_meters)}m)")

        return {
            "on_route": on_route,
            "getting_closer": getting_closer,
            "dist_to_goal_meters": round(current_dist, 1)
        }

if __name__ == "__main__":
    # Example usage
    START = (49.2606, -123.2460)
    DESTINATION = (49.2827, -123.1207)
    
    checker = RouteChecker(start=START, destination=DESTINATION)
    
    # Simulate moving
    print("\n--- Simulating Movement ---")
    checker.check_position(49.2606, -123.2460)
    checker.check_position(49.2610, -123.2460)