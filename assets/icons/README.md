# cleanCT · Brand Identity, High-Definition Icons & In-App Banners
### Non-Destructive Wood CT Metal-Base Removal & Inspection Suite

This directory contains the production-ready high-definition icons, taskbar mipmaps, window titlebar assets, and in-app banners designed specifically for **cleanCT**.

---

## 1. Brand Identity: **cleanCT**

- **Name**: **cleanCT**
- **Descriptor**: *Non-Destructive Wood CT Metal-Base Removal & Inspection Suite*
- **Typographic Treatment**:
  - `clean`: Rendered in crisp, modern, ultra-clean white sans-serif.
  - `CT`: Capitalized in warm glowing amber-gold (`#f2b23c`), matching the wood ROI and tomographic density palette.
- **Brand Purpose**:
  - Eliminates harsh beam-hardening and high-attenuation metal streak artifacts by cleanly detaching the mounting base platform.
  - Preserves 100% of the precious organic wood specimen block undamaged for downstream refined micro-tomographic inspection.

---

## 2. Visual Symbolism & Icon Architecture

```
+-------------------------------------------------------------+
|  [Wood Cuboid Block]  Glowing Amber Voxel Grain Block       |
|                       100% Intact, Preserved & Undamaged    |
|                                                             |
|  [Wood ROI Seam]      Luminous Amber Boundary Contour       |
|                       Surgical, Non-Destructive Interface   |
|                                                             |
|  [Metal Base Disc]    Thin Silver Mounting Platform Plate   |
|                       Gently Separating & Lowering Away     |
|                                                             |
|  [Brand Badge]        cleanCT (Modern Typography)           |
+-------------------------------------------------------------+
```

1. **Intact Wood Cuboid Block**:
   - A 3D rectangular timber block with glowing golden-amber (`#f2b23c`) concentric annual growth rings on top and vertical vascular fiber grain on the sides.
2. **Amber Wood ROI Seam**:
   - A delicate luminous amber contour outline hugging the base of the wood block, directly reflecting the 2D axial viewer's `wood ROI (amber)` detection.
3. **Detached Silver Base Plate**:
   - A thin circular brushed-metal aluminum mounting plate (`metal (silver)`) gently dropping away below the block, signifying non-destructive base isolation.
4. **Integrated "cleanCT" Typography**:
   - Modern, professional branding integrated cleanly onto the bottom section of the titanium squircle badge.
5. **Beveled Titanium Squircle**:
   - Modern Windows 11 Fluent and macOS compatible squircle tile with smooth anti-aliased alpha transparency.

---

## 3. Production Asset Inventory

All files are structured inside this directory:

### Standard Desktop & Taskbar Icons (`icons/`)
| File | Dimensions | Purpose / Target | Format |
| :--- | :--- | :--- | :--- |
| **`app.ico`** | **16, 24, 32, 48, 64, 128, 256** | **Windows Explorer, Taskbar, Desktop Shortcut** | Multi-res ICO (32-bit RGBA) |
| `icon_16x16.png` | 16 × 16 px | Window titlebar (100% DPI), small system tray | RGBA PNG |
| `icon_24x24.png` | 24 × 24 px | Titlebar & taskbar (125% DPI scaling) | RGBA PNG |
| `icon_32x32.png` | 32 × 32 px | Windows taskbar (100% DPI), standard titlebar | RGBA PNG |
| `icon_48x48.png` | 48 × 48 px | Windows desktop standard icon | RGBA PNG |
| `icon_64x64.png` | 64 × 64 px | High-DPI taskbar (200% scaling / 4K) | RGBA PNG |
| `icon_128x128.png` | 128 × 128 px | Large desktop shortcut | RGBA PNG |
| `icon_256x256.png` | 256 × 256 px | App header logo & drop-in for `assets/app_icon_256.png` | RGBA PNG |
| `icon_512x512.png` | 512 × 512 px | Microsoft Store / installer splash screen | RGBA PNG |
| `icon_1024x1024.png` | 1024 × 1024 px | Master HD transparent squircle | RGBA PNG |

### Point-Cloud Voxel Variants (`icons/variants/`)
- `app_pointcloud.ico`: Multi-res Windows ICO featuring the amber point-cloud voxel block.
- `icon_pointcloud_1024x1024.png`: Master HD point-cloud icon with "cleanCT" typography.
- `icon_pointcloud_256x256.png`, `icon_pointcloud_64x64.png`, `icon_pointcloud_32x32.png`.

### In-App & Promotional Banners (`icons/banners/`)
| File | Dimensions | Purpose | Format |
| :--- | :--- | :--- | :--- |
| `banner_16x9_1920x1080.png` | 1920 × 1080 px | Full HD promotional splash & presentation banner | RGB PNG |
| `banner_16x9_1376x768.png` | 1376 × 768 px | Native HD widescreen banner with telemetry HUD | RGB PNG |
| `banner_header_1200x400.png` | 1200 × 400 px | In-app main workspace top header banner | RGB PNG |
| `banner_sidebar_300x120.png` | 300 × 120 px | Compact sidebar brand card / logo banner | RGB PNG |

### Solid Background Tiles (`icons/solid/`)
- `icon_solid_1024x1024.png`, `icon_solid_256x256.png`, `icon_solid_64x64.png`, `icon_solid_32x32.png`

### Raw Master AI Renders (`icons/raw/`)
- `cleanct_master_app_icon.jpg`: Solid wood block with detached base and cleanCT typography.
- `cleanct_master_pointcloud_icon.jpg`: 3D point-cloud voxel block with cleanCT typography.
- `cleanct_master_banner.jpg`: Widescreen telemetry banner matching app KPIs.

---

## 4. Image Generation Prompts Used

### 1. Primary cleanCT Desktop App Icon:
```text
Professional modern desktop application icon for scientific software named "cleanCT". Centered inside a sleek dark titanium squircle frame. In the center is a 3D rectangular cuboid wood specimen block with glowing amber-gold wood grain and fine vertical striations, 100 percent intact and undamaged. Below it, a thin circular brushed-silver metal base plate gently detaches and drops downward, with a glowing amber ROI contour line at the interface. Tastefully integrated below the specimen inside the icon badge is the modern brand name "cleanCT" in elegant, crisp typography (lowercase "clean" in sleek white, capitalized "CT" in glowing amber). High-end industrial design, raytraced lighting, luxury dark mode, 8k.
```

### 2. Point-Cloud cleanCT App Icon:
```text
Professional luxury desktop application icon for scientific software named "cleanCT". Centered inside a sleek dark titanium squircle frame. In the center is a 3D rectangular cuboid block made of glowing amber-gold voxel point-cloud fibers and anatomical wood growth rings, 100 percent intact and whole. Below the wood block, a thin circular brushed-silver metallic base plate separates and lowers downward, with a glowing amber ROI contour square outlining the bottom face. At the bottom of the badge is the modern app name "cleanCT" in crisp, elegant typography (clean in white, CT in amber glow). Minimalist, modern Apple and Windows 11 Fluent aesthetic, raytraced lighting, 8k.
```

### 3. cleanCT In-App Widescreen Banner (16:9):
```text
Cinematic wide in-app header banner for scientific micro-CT desktop software named "cleanCT". Dark graphite laboratory theme. In the center: a high-resolution 3D visualization of a rectangular cuboid wood block specimen with glowing amber-gold voxel point-cloud fibers and anatomical tree ring striations, completely intact, pristine, and preserved. At the very bottom base, a thin circular brushed-silver metallic mounting platform plate gently separates and lowers away, demarcated by a delicate glowing amber boundary contour outline. In the background: subtle micro-CT tomographic arcs, slice telemetry readouts reading 'Wood Preserved: 94.1%, Metal Base Removed: 5.9%, Ground Truth: Match', and elegant typography reading 'cleanCT' (clean in crisp white, CT in amber glow) with subtitle 'Non-Destructive Wood CT Metal-Base Removal & Inspection'. 8k, scientific visualization.
```

---

## 5. Non-Interfering Integration Instructions

> [!TIP]
> Whenever current pipeline processing finishes:
> 1. Copy `icons/app.ico` -> `assets/app.ico`
> 2. Copy `icons/icon_256x256.png` -> `assets/app_icon_256.png`
> 3. In `web/index.html`, update the `<title>` and header branding text to **cleanCT**.
