"""Generate emulator tracks from public OSRM driving routes (not recorded drives)."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def main():
    output = Path(__file__).resolve().parent.parent / "docs/routes"
    output.mkdir(parents=True, exist_ok=True)
    routes = []
    for name, origin in (("A-seoul-to-gangneung", (126.9780, 37.5665)),
                         ("B-daejeon-to-gangneung", (127.3845, 36.3504))):
        url = (f"https://router.project-osrm.org/route/v1/driving/{origin[0]},{origin[1]};128.8759,37.7521"
               "?overview=full&geometries=geojson&annotations=duration&steps=false")
        request = Request(url, headers={"User-Agent": "PleosConvoyLocalTest/0.1"})
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        assert result["code"] == "Ok", result
        route = result["routes"][0]
        coordinates = route["geometry"]["coordinates"]
        durations = [d for leg in route["legs"] for d in leg["annotation"]["duration"]]
        assert len(coordinates) > 2 and len(durations) == len(coordinates) - 1
        assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in coordinates)
        gpx = ET.Element("gpx", version="1.1", creator="PleosConvoyLocalTest / OSRM",
                         xmlns="http://www.topografix.com/GPX/1/1")
        metadata = ET.SubElement(gpx, "metadata")
        ET.SubElement(metadata, "desc").text = "Synthetic driving track. Route: OSRM; map data: OpenStreetMap contributors. Estimated times, not a recorded drive."
        link = ET.SubElement(metadata, "link", href="https://www.openstreetmap.org/copyright")
        ET.SubElement(link, "text").text = "OpenStreetMap contributors"
        track = ET.SubElement(gpx, "trk")
        ET.SubElement(track, "name").text = name
        segment = ET.SubElement(track, "trkseg")
        start = datetime.now(timezone.utc).replace(microsecond=0)
        elapsed = 0.0
        for index, (lon, lat) in enumerate(coordinates):
            if index:
                elapsed += max(0.001, durations[index - 1])
            point = ET.SubElement(segment, "trkpt", lat=f"{lat:.7f}", lon=f"{lon:.7f}")
            ET.SubElement(point, "ele").text = "0"
            ET.SubElement(point, "time").text = (start + timedelta(seconds=elapsed)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        document = ET.SubElement(kml, "Document")
        placemark = ET.SubElement(document, "Placemark")
        ET.SubElement(placemark, "name").text = name
        ET.SubElement(placemark, "description").text = "Synthetic OSRM driving route; © OpenStreetMap contributors. Not a recorded drive."
        line = ET.SubElement(placemark, "LineString")
        ET.SubElement(line, "tessellate").text = "1"
        ET.SubElement(line, "coordinates").text = " ".join(f"{lon},{lat},0" for lon, lat in coordinates)
        for suffix, tree in (("gpx", gpx), ("kml", kml)):
            path = output / f"{name}.{suffix}"
            ET.ElementTree(tree).write(path, encoding="utf-8", xml_declaration=True)
            ET.parse(path)
        routes.append({"name": name, "url": url, "points": len(coordinates),
                       "distance_km": round(route["distance"] / 1000, 2),
                       "estimated_minutes": round(route["duration"] / 60, 1),
                       "snapped_start_lon_lat": coordinates[0], "snapped_end_lon_lat": coordinates[-1],
                       "generated_at": start.isoformat()})
        print(json.dumps(routes[-1]), flush=True)
        time.sleep(1.1)  # Public demo policy: at most one request per second.
    (output / "routes-source.json").write_text(json.dumps(routes, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
