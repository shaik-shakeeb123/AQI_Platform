Add-Type -AssemblyName System.Drawing

$sourcePath = "C:\Users\shaik shakeeb\.gemini\antigravity\brain\c81b4846-c2ca-4971-9a45-824520cc7e81\master_logo_1784398913007.png"
$destDir = "d:\AQI_Platform\AQI_Platform_V01\AQI_Platform_V01\aqi-app\public"

$sizes = @(16, 32, 48, 180, 192, 512)
$img = [System.Drawing.Image]::FromFile($sourcePath)

foreach ($size in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $graph = [System.Drawing.Graphics]::FromImage($bmp)
    
    # Set high quality resizing
    $graph.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graph.DrawImage($img, 0, 0, $size, $size)
    
    $destPath = Join-Path -Path $destDir -ChildPath "logo${size}.png"
    if ($size -eq 16) { $destPath = Join-Path -Path $destDir -ChildPath "favicon-16x16.png" }
    if ($size -eq 32) { $destPath = Join-Path -Path $destDir -ChildPath "favicon-32x32.png" }
    if ($size -eq 48) { $destPath = Join-Path -Path $destDir -ChildPath "favicon-48x48.png" }
    if ($size -eq 180) { $destPath = Join-Path -Path $destDir -ChildPath "apple-touch-icon.png" }

    $bmp.Save($destPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graph.Dispose()
    $bmp.Dispose()
    Write-Output "Generated $destPath"
}

$img.Dispose()
