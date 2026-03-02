# test_example_geofence_map.py
import folium
from shapely.geometry import Polygon
from geofence_service import geofence_service

# 1) Define test polygon (lon, lat order for Shapely)
storm_box = Polygon([
    (-92.10, 30.12),
    (-91.95, 30.12),
    (-91.95, 30.26),
    (-92.10, 30.26),
    (-92.10, 30.12)
])

# 2) Inject into cache
geofence_service.set_polygons([{
    "event": "Test Storm",
    "severity": "Severe",
    "geometry": storm_box.__geo_interface__,
    "polygon": storm_box
}])

# 3) Test points
inside_lat, inside_lon   = 30.20, -92.02
outside_lat, outside_lon = 30.30, -92.20

inside, event, severity = geofence_service.check_location(inside_lat, inside_lon, count_boundary_as_inside=True)
outside, _, _           = geofence_service.check_location(outside_lat, outside_lon, count_boundary_as_inside=True)

print("Inside result:", inside, event, severity)
print("Outside result:", outside)

# 4) Build map centered between points
m = folium.Map(location=[30.20, -92.02], zoom_start=11)

# Draw polygon: Folium expects (lat, lon)
folium.Polygon(
    locations=[(lat, lon) for lon, lat in storm_box.exterior.coords],
    color="red", weight=2, fill=True, fill_opacity=0.25,
    popup="Test Storm | Severe"
).add_to(m)

# Add test markers
folium.Marker([inside_lat, inside_lon], popup=f"Inside: {inside}", icon=folium.Icon(color="green")).add_to(m)
folium.Marker([outside_lat, outside_lon], popup=f"Inside: {outside}", icon=folium.Icon(color="blue")).add_to(m)

m.save("test_example_geofence.html")
print("Saved map → test_example_geofence.html")
