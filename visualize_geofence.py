import folium
from shapely.geometry import Polygon
from geofence_service import geofence_service

# Create your test polygon
poly = Polygon([
    (-89.20, 39.80),
    (-89.00, 39.80),
    (-89.00, 39.95),
    (-89.20, 39.95),
    (-89.20, 39.80)
])

# Inject it
geofence_service.cached_polygons = [{
    "event": "Test Storm",
    "severity": "Severe",
    "geometry": {},
    "polygon": poly
}]

# Test location
lat = 39.87253
lon = -89.10594

# Create map centered on the test point
m = folium.Map(location=[lat, lon], zoom_start=10)

# Add polygon to map
folium.Polygon(
    locations=[(y, x) for x, y in poly.exterior.coords],
    color="red",
    weight=3,
    fill=True,
    fill_opacity=0.3
).add_to(m)

# Add test point
folium.Marker(
    location=[lat, lon],
    popup="Test Location",
    icon=folium.Icon(color="blue")
).add_to(m)

# Save map
m.save("geofence_test_map.html")

print("Map saved as geofence_test_map.html")
