from geofence_service import geofence_service

# Load the latest Day 3 WPC polygons (KMZ)
loaded = geofence_service.load_wpc_kmz(day=3, replace_cache=True)
print("Loaded:", loaded)

# Test a sample location
lat = 34.6
lon = -98.4
inside, event, severity = geofence_service.check_location(lat, lon, count_boundary_as_inside=True)
print("Inside:", inside, "| Event:", event, "| Severity:", severity)
