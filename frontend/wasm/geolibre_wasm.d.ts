/* tslint:disable */
/* eslint-disable */

/**
 * Builder for encoding a Cloud Optimized GeoTIFF (tiled, with overviews and
 * GDAL ghost metadata) to bytes. A COG is also a valid plain GeoTIFF.
 *
 * Configure with the `set_*` methods, then call one of `write_*` with the
 * pixel data to get a `Uint8Array` of the encoded file.
 */
export class CogBuilder {
    free(): void;
    [Symbol.dispose](): void;
    /**
     * New builder for a `width` x `height` raster with `bands` bands.
     */
    constructor(width: number, height: number, bands: number);
    /**
     * Force BigTIFF (64-bit offsets) for very large outputs.
     */
    set_bigtiff(on: boolean): void;
    /**
     * Compression: `none`, `lzw`, `deflate`, `packbits`, `webp`, `jpeg`, `jpegxl`.
     */
    set_compression(name: string): void;
    /**
     * Set the EPSG code (1..=65535).
     */
    set_epsg(epsg: number): void;
    /**
     * Set the full affine geo-transform:
     * `[x_origin, pixel_width, row_rotation, y_origin, col_rotation, pixel_height]`.
     */
    set_geo_transform(gt: Float64Array): void;
    /**
     * Set the no-data sentinel value.
     */
    set_nodata(v: number): void;
    /**
     * Convenience: north-up geo-transform from upper-left origin and pixel size.
     */
    set_origin(x_min: number, y_max: number, pixel_size: number): void;
    /**
     * Explicit overview decimation factors (e.g. `[2,4,8]`); empty disables overviews.
     */
    set_overview_levels(levels: Uint32Array): void;
    /**
     * Internal tile size in pixels (default 512).
     */
    set_tile_size(px: number): void;
    /**
     * Encode `f32` pixel data to a COG. `Uint8Array`.
     */
    write_f32(data: Float32Array): Uint8Array;
    /**
     * Encode `f64` pixel data to a COG. `Uint8Array`.
     */
    write_f64(data: Float64Array): Uint8Array;
    /**
     * Encode `u8` pixel data to a COG. `Uint8Array`.
     */
    write_u8(data: Uint8Array): Uint8Array;
}

/**
 * Range-request reader for a (tiled) Cloud Optimized GeoTIFF.
 *
 * The wasm module does no network I/O itself; this class parses the header and
 * tells the JS host exactly which byte ranges to fetch, then decodes the tiles
 * the host fetches. Typical flow:
 *
 * 1. Range-fetch the first chunk of the file (e.g. 0..1 MiB) and
 *    `new CogStream(headerBytes)`. If it throws "need more header bytes", fetch
 *    a larger prefix and retry.
 * 2. Pick a level (0 = full res, higher = overviews) and a pixel window.
 * 3. `tiles_for_window(level, x, y, w, h)` returns the tiles and their byte
 *    ranges; range-fetch each, then `decode_tile_f64(level, bytes)`.
 */
export class CogStream {
    free(): void;
    [Symbol.dispose](): void;
    /**
     * Bounding box `[min_x, min_y, max_x, max_y]` in the dataset CRS, or empty.
     */
    bounding_box(): Float64Array;
    /**
     * Bounds `[min_lon, min_lat, max_lon, max_lat]` in WGS84 degrees, or empty.
     */
    bounds_lonlat(): Float64Array;
    /**
     * Image center `[x, y]` in the dataset CRS, or empty.
     */
    center(): Float64Array;
    /**
     * Image center `[lon, lat]` in WGS84 degrees, or empty if not convertible.
     */
    center_lonlat(): Float64Array;
    /**
     * Decode one tile's fetched (compressed) bytes into an `f64` `Float64Array`,
     * pixel-interleaved, length `tile_width * tile_height * bands`. Edge tiles
     * come back full-size; clip to the image/window on the JS side.
     */
    decode_tile_f64(level: number, tile_bytes: Uint8Array): Float64Array;
    /**
     * Level-0 geo-transform `[x_origin, pixel_width, row_rot, y_origin, col_rot,
     * pixel_height]`, or empty if not georeferenced.
     */
    geo_transform(): Float64Array;
    /**
     * JSON array describing every level: `[{level,width,height,tile_width,
     * tile_height,tiles_x,tiles_y,bands,bits_per_sample,sample_format,compression}]`.
     */
    levels_json(): string;
    /**
     * Parse a COG's tile layout from front-of-file header bytes.
     */
    constructor(header_bytes: Uint8Array);
    /**
     * `[offset, length]` byte range of the tile at `(col, row)` on `level`.
     */
    tile_range(level: number, col: number, row: number): Float64Array;
    /**
     * Tiles covering a pixel window on `level`, as a JSON array of
     * `{col,row,offset,length}`. Fetch each byte range, then `decode_tile_f64`.
     */
    tiles_for_window(level: number, x: number, y: number, w: number, h: number): string;
    /**
     * EPSG code of the full-resolution level, if any.
     */
    readonly epsg: number | undefined;
    /**
     * No-data sentinel, if declared.
     */
    readonly nodata: number | undefined;
    /**
     * Number of resolution levels (1 + overview count).
     */
    readonly num_levels: number;
}

/**
 * A parsed GeoTIFF held in memory. Construct once, then call the accessor and
 * `read_*` methods many times without re-parsing the file.
 */
export class GeoTiffReader {
    free(): void;
    [Symbol.dispose](): void;
    /**
     * Bounding box as `[min_x, min_y, max_x, max_y]`, or empty if not georeferenced.
     */
    bounding_box(): Float64Array;
    /**
     * Bounds `[min_lon, min_lat, max_lon, max_lat]` in WGS84 degrees, or empty
     * if not convertible.
     */
    bounds_lonlat(): Float64Array;
    /**
     * Image center `[x, y]` in the dataset CRS, or empty if not georeferenced.
     */
    center(): Float64Array;
    /**
     * Image center `[lon, lat]` in WGS84 degrees, or empty if not georeferenced
     * or the CRS is not convertible.
     */
    center_lonlat(): Float64Array;
    /**
     * Affine geo-transform as `[x_origin, pixel_width, row_rotation,
     * y_origin, col_rotation, pixel_height]`, or an empty array if absent.
     */
    geo_transform(): Float64Array;
    /**
     * Full metadata as a JSON string (same shape as [`geotiff_info`]).
     */
    info_json(): string;
    /**
     * Parse a GeoTIFF / BigTIFF / COG from raw bytes.
     */
    constructor(data: Uint8Array);
    /**
     * Read every band as `f64`, interleaved per pixel (`band0,band1,...`).
     */
    read_all_f64(): Float64Array;
    /**
     * Read a band's raw, undecoded-to-native bytes. `Uint8Array`.
     */
    read_band_bytes(band: number): Uint8Array;
    /**
     * Native `f32` band. `Float32Array`.
     */
    read_band_f32(band: number): Float32Array;
    /**
     * Read a band as `f64`, converting from any on-disk type. `Float64Array`.
     */
    read_band_f64(band: number): Float64Array;
    /**
     * Native `i16` band. `Int16Array`.
     */
    read_band_i16(band: number): Int16Array;
    /**
     * Native `i32` band. `Int32Array`.
     */
    read_band_i32(band: number): Int32Array;
    /**
     * Native `i8` band. `Int8Array`.
     */
    read_band_i8(band: number): Int8Array;
    /**
     * Native `u16` band. `Uint16Array`.
     */
    read_band_u16(band: number): Uint16Array;
    /**
     * Native `u32` band. `Uint32Array`.
     */
    read_band_u32(band: number): Uint32Array;
    /**
     * Native `u8` band. `Uint8Array`.
     */
    read_band_u8(band: number): Uint8Array;
    /**
     * Band-0 statistics as a JSON string (same shape as [`geotiff_stats`]).
     */
    stats_json(): string;
    /**
     * GDAL value transform as `[scale, offset]` (physical = raw*scale+offset),
     * or empty if none. Apply to `read_*` outputs to get physical values.
     */
    value_transform(): Float64Array;
    readonly bands: number;
    readonly bits_per_sample: number;
    readonly compression: string;
    /**
     * EPSG code, or `undefined` if the file is not georeferenced by EPSG.
     */
    readonly epsg: number | undefined;
    readonly height: number;
    readonly is_bigtiff: boolean;
    /**
     * No-data sentinel, or `undefined` if none is declared.
     */
    readonly nodata: number | undefined;
    readonly sample_format: string;
    readonly width: number;
}

/**
 * Install a panic hook so Rust panics surface as readable `console.error`
 * messages instead of an opaque `RuntimeError: unreachable`.
 */
export function __start(): void;

/**
 * Convex hull of a 2D point set. Input is `[x0,y0,x1,y1,...]`; output is the
 * hull ring as `[x0,y0,...]` (closed). Needs at least 3 points.
 */
export function convex_hull(points_xy: Float64Array): Float64Array;

/**
 * Decode only a GeoTIFF's header and return its metadata as JSON. O(header)
 * memory, so it works on multi-gigabyte rasters that whole-image reads cannot
 * fit in WASM's 4 GiB address space.
 *
 * `{"ok":true,"width","height","bands","epsg"|null,"nodata"|null,
 *   "bits_per_sample","sample_format","compression","tiled","bigtiff"}`
 */
export function geotiff_info(data: Uint8Array): string;

/**
 * Read a single band of pixel values as an `f64` `Float64Array` (any on-disk
 * sample format is converted), row-major, length `width * height`.
 */
export function geotiff_read_band_f64(data: Uint8Array, band: number): Float64Array;

/**
 * Decode a GeoTIFF and return band-0 summary statistics as JSON:
 * `{"ok":true,"width","height","bands","epsg","valid","min","max","mean"}`.
 */
export function geotiff_stats(data: Uint8Array): string;

/**
 * LiDAR formats this build can read from memory.
 */
export function lidar_formats(): string;

/**
 * Read a LiDAR file's metadata as JSON. For LAS/LAZ this is header-only (count,
 * bounds, CRS, point format, COPC flag) and never decodes points:
 * `{"ok":true,"format","points","epsg"|null,"point_format"|null,
 *   "bounds":[min_x,min_y,min_z,max_x,max_y,max_z]|null,"copc":bool}`.
 */
export function lidar_info(data: Uint8Array, format: string): string;

/**
 * Read per-point classification codes as a `Uint8Array` (length `point_count`).
 */
export function lidar_read_classification(data: Uint8Array, format: string): Uint8Array;

/**
 * Read per-point intensity as a `Uint16Array` (length `point_count`).
 */
export function lidar_read_intensity(data: Uint8Array, format: string): Uint16Array;

/**
 * Read all point coordinates as an interleaved `Float64Array`
 * `[x0,y0,z0, x1,y1,z1, ...]` (length `3 * point_count`).
 *
 * Guarded against 32-bit memory blowup; very large clouds return a clean error
 * (read the header with `lidar_info`, or downsample on your side).
 */
export function lidar_read_xyz(data: Uint8Array, format: string): Float64Array;

/**
 * Global Moran's I spatial autocorrelation for point data, using a binary
 * distance-band spatial weights matrix (neighbors within `distance_threshold`).
 *
 * `points_xy` is `[x0,y0,...]`, `values` is one value per point. Returns JSON:
 * `{"ok":true,"morans_i","expected","variance","z_score","p_value","n"}`.
 *
 * Builds neighbors in O(n^2); intended for up to a few thousand points.
 */
export function morans_i(points_xy: Float64Array, values: Float64Array, distance_threshold: number): string;

/**
 * Vector formats this build can read from memory (comma-separated).
 */
export function vector_formats(): string;

/**
 * Read a vector dataset and return metadata as JSON:
 * `{"ok":true,"name","features","geometry","epsg"|null,"fields":[...],
 *   "bbox":[min_x,min_y,max_x,max_y]|null}`.
 */
export function vector_info(data: Uint8Array, format: string): string;

/**
 * Read a vector dataset and return it as a GeoJSON `FeatureCollection` string.
 */
export function vector_to_geojson(data: Uint8Array, format: string): string;

/**
 * Read a vector dataset, reproject it to `dst_epsg`, and return GeoJSON.
 * Uses the bundled pure-Rust projection engine (full EPSG support).
 *
 * `src_epsg` overrides the source CRS: pass `0` to use the layer's own CRS, or
 * fall back to EPSG:4326 if it declares none (GeoJSON is WGS84 by RFC 7946).
 */
export function vector_to_geojson_reproject(data: Uint8Array, format: string, dst_epsg: number, src_epsg: number): string;

/**
 * Semantic version of this crate, exposed for runtime feature detection.
 */
export function version(): string;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __start: () => void;
    readonly __wbg_cogbuilder_free: (a: number, b: number) => void;
    readonly __wbg_cogstream_free: (a: number, b: number) => void;
    readonly __wbg_geotiffreader_free: (a: number, b: number) => void;
    readonly cogbuilder_new: (a: number, b: number, c: number) => number;
    readonly cogbuilder_set_bigtiff: (a: number, b: number) => void;
    readonly cogbuilder_set_compression: (a: number, b: number, c: number, d: number) => void;
    readonly cogbuilder_set_epsg: (a: number, b: number) => void;
    readonly cogbuilder_set_geo_transform: (a: number, b: number, c: number, d: number) => void;
    readonly cogbuilder_set_nodata: (a: number, b: number) => void;
    readonly cogbuilder_set_origin: (a: number, b: number, c: number, d: number) => void;
    readonly cogbuilder_set_overview_levels: (a: number, b: number, c: number) => void;
    readonly cogbuilder_set_tile_size: (a: number, b: number) => void;
    readonly cogbuilder_write_f32: (a: number, b: number, c: number, d: number) => void;
    readonly cogbuilder_write_f64: (a: number, b: number, c: number, d: number) => void;
    readonly cogbuilder_write_u8: (a: number, b: number, c: number, d: number) => void;
    readonly cogstream_bounding_box: (a: number, b: number) => void;
    readonly cogstream_bounds_lonlat: (a: number, b: number) => void;
    readonly cogstream_center: (a: number, b: number) => void;
    readonly cogstream_center_lonlat: (a: number, b: number) => void;
    readonly cogstream_decode_tile_f64: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly cogstream_epsg: (a: number) => number;
    readonly cogstream_geo_transform: (a: number, b: number) => void;
    readonly cogstream_levels_json: (a: number, b: number) => void;
    readonly cogstream_new: (a: number, b: number, c: number) => void;
    readonly cogstream_nodata: (a: number, b: number) => void;
    readonly cogstream_num_levels: (a: number) => number;
    readonly cogstream_tile_range: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly cogstream_tiles_for_window: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => void;
    readonly convex_hull: (a: number, b: number, c: number) => void;
    readonly geotiff_info: (a: number, b: number, c: number) => void;
    readonly geotiff_read_band_f64: (a: number, b: number, c: number, d: number) => void;
    readonly geotiff_stats: (a: number, b: number, c: number) => void;
    readonly geotiffreader_bands: (a: number) => number;
    readonly geotiffreader_bits_per_sample: (a: number) => number;
    readonly geotiffreader_bounding_box: (a: number, b: number) => void;
    readonly geotiffreader_bounds_lonlat: (a: number, b: number) => void;
    readonly geotiffreader_center: (a: number, b: number) => void;
    readonly geotiffreader_center_lonlat: (a: number, b: number) => void;
    readonly geotiffreader_compression: (a: number, b: number) => void;
    readonly geotiffreader_epsg: (a: number) => number;
    readonly geotiffreader_geo_transform: (a: number, b: number) => void;
    readonly geotiffreader_height: (a: number) => number;
    readonly geotiffreader_info_json: (a: number, b: number) => void;
    readonly geotiffreader_is_bigtiff: (a: number) => number;
    readonly geotiffreader_new: (a: number, b: number, c: number) => void;
    readonly geotiffreader_nodata: (a: number, b: number) => void;
    readonly geotiffreader_read_all_f64: (a: number, b: number) => void;
    readonly geotiffreader_read_band_bytes: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_f32: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_f64: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_i16: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_i32: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_i8: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_u16: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_u32: (a: number, b: number, c: number) => void;
    readonly geotiffreader_read_band_u8: (a: number, b: number, c: number) => void;
    readonly geotiffreader_sample_format: (a: number, b: number) => void;
    readonly geotiffreader_stats_json: (a: number, b: number) => void;
    readonly geotiffreader_value_transform: (a: number, b: number) => void;
    readonly geotiffreader_width: (a: number) => number;
    readonly lidar_formats: (a: number) => void;
    readonly lidar_info: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly lidar_read_classification: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly lidar_read_intensity: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly lidar_read_xyz: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly morans_i: (a: number, b: number, c: number, d: number, e: number, f: number) => void;
    readonly vector_formats: (a: number) => void;
    readonly vector_info: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly vector_to_geojson: (a: number, b: number, c: number, d: number, e: number) => void;
    readonly vector_to_geojson_reproject: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => void;
    readonly version: (a: number) => void;
    readonly rust_zstd_wasm_shim_calloc: (a: number, b: number) => number;
    readonly rust_zstd_wasm_shim_free: (a: number) => void;
    readonly rust_zstd_wasm_shim_malloc: (a: number) => number;
    readonly rust_zstd_wasm_shim_memcmp: (a: number, b: number, c: number) => number;
    readonly rust_zstd_wasm_shim_memcpy: (a: number, b: number, c: number) => number;
    readonly rust_zstd_wasm_shim_memmove: (a: number, b: number, c: number) => number;
    readonly rust_zstd_wasm_shim_memset: (a: number, b: number, c: number) => number;
    readonly rust_zstd_wasm_shim_qsort: (a: number, b: number, c: number, d: number) => void;
    readonly __wbindgen_export: (a: number, b: number, c: number) => void;
    readonly __wbindgen_export2: (a: number, b: number) => number;
    readonly __wbindgen_export3: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_add_to_stack_pointer: (a: number) => number;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
