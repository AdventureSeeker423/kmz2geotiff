import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from osgeo import gdal

gdal.UseExceptions()  # Prevents GDAL warning about exceptions

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FOLDER = os.path.join(SCRIPT_DIR, "Converted GeoTIFFs")
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

LOG_FILE = os.path.join(OUTPUT_FOLDER, "conversion_log.txt")

# Keep track of results
success_list = []
failed_list = []
skipped_list = []  # Track skipped files


def convert_kmz(kmz_path):
    base = os.path.splitext(os.path.basename(kmz_path))[0]
    out_tif = os.path.join(OUTPUT_FOLDER, f"{base}.tif")

    # ✅ Skip if output already exists
    if os.path.exists(out_tif):
        print(f"\n⏭️ Skipping {base} (already exists)")
        skipped_list.append(base)
        return

    print(f"\nProcessing {base} ...")

    try:
        # Unzip KMZ
        tmp_dir = os.path.join(OUTPUT_FOLDER, "_temp", base)
        os.makedirs(tmp_dir, exist_ok=True)
        with zipfile.ZipFile(kmz_path, "r") as z:
            z.extractall(tmp_dir)

        # Find KML
        kml_files = [f for f in os.listdir(tmp_dir) if f.lower().endswith(".kml")]
        if not kml_files:
            raise Exception("No KML found")
        kml_path = os.path.join(tmp_dir, kml_files[0])

        # Parse KML
        tree = ET.parse(kml_path)
        root = tree.getroot()

        kml_ns = "http://www.opengis.net/kml/2.2"
        gx_ns = "http://www.google.com/kml/ext/2.2"

        # Find LatLonQuad coordinates
        latlon_quad = root.find(f".//{{{gx_ns}}}LatLonQuad/{{{kml_ns}}}coordinates")
        if latlon_quad is None:
            raise Exception("No LatLonQuad found")

        coords = [tuple(map(float, c.split(","))) for c in latlon_quad.text.strip().split()]
        if len(coords) != 4:
            raise Exception("LatLonQuad does not have 4 points")

        # Find GroundOverlay image
        go = root.find(f".//{{{kml_ns}}}GroundOverlay")
        icon = go.find(f"{{{kml_ns}}}Icon/{{{kml_ns}}}href")
        img_file = os.path.join(tmp_dir, icon.text.replace("/", os.sep))
        if not os.path.exists(img_file):
            raise Exception(f"Image file not found: {img_file}")

        # Open image and assign GCPs
        ds = gdal.Open(img_file)
        if ds is None:
            raise Exception("Failed to open image file")
        width, height = ds.RasterXSize, ds.RasterYSize

        gcps = [
            gdal.GCP(coords[0][0], coords[0][1], 0, 0, height),
            gdal.GCP(coords[1][0], coords[1][1], 0, width, height),
            gdal.GCP(coords[2][0], coords[2][1], 0, width, 0),
            gdal.GCP(coords[3][0], coords[3][1], 0, 0, 0),
        ]

        # Step 1: Translate image with GCPs
        tmp_tif = os.path.join(OUTPUT_FOLDER, f"{base}_with_gcps.tif")
        gdal.Translate(tmp_tif, ds, GCPs=gcps, outputSRS="EPSG:4326")

        # Step 2: Warp image with compression and tiling
        gdal.Warp(
            out_tif,
            tmp_tif,
            dstSRS="EPSG:4326",
            tps=True,
            options=gdal.WarpOptions(
                creationOptions=[
                    "TILED=YES",
                    "COMPRESS=JPEG",
                    "JPEG_QUALITY=50",
                    "BIGTIFF=IF_SAFER",
                    "BLOCKXSIZE=512",
                    "BLOCKYSIZE=512",
                ]
            ),
        )

        os.remove(tmp_tif)
        success_list.append(base)
        print(f"  ✅ Saved GeoTIFF: {out_tif}")

    except Exception as e:
        failed_list.append(base)
        print(f"  ❌ Failed: {base} → {e}")


def log_successful_conversions():
    if not success_list:
        return  # Nothing to log

    # Sort alphabetically and remove duplicates
    sorted_names = sorted(set(success_list))

    timestamp = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"\n--- Conversion on {timestamp} ---\n")
        for name in sorted_names:
            log.write(f"{name}\n")
        log.write("\n")  # Extra spacing between runs

    #print(f"\n📝 Log updated: {LOG_FILE}")


def main():
    kmz_files = [f for f in os.listdir(SCRIPT_DIR) if f.lower().endswith(".kmz")]
    if not kmz_files:
        print("No KMZ files found in:", SCRIPT_DIR)
        return

    for kmz in kmz_files:
        convert_kmz(os.path.join(SCRIPT_DIR, kmz))

    print("\n──────────────────────────────")
    if success_list:
        print("✅ Successful:", ", ".join(success_list))
    if skipped_list:
        print("⏭️ Skipped:", ", ".join(skipped_list))
    if failed_list:
        print("❌ Failed:", ", ".join(failed_list))
    print("──────────────────────────────")
    print("✅ CONVERSION COMPLETE ✅")
    print("New Files Located:", OUTPUT_FOLDER)

    # Write log of successful conversions
    log_successful_conversions()




if __name__ == "__main__":
    main()
