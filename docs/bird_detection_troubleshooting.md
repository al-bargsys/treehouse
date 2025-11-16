# Bird Detection Troubleshooting Guide

## Issue: Birds Not Being Detected

If you physically see birds on the feeder but they're not being detected, check the following:

### 1. Class ID Mismatch (FIXED)

**Problem**: The detection service was using COCO dataset class IDs (bird=14) but your custom trained model uses different class IDs (bird=1).

**Solution**: The detection service now supports configurable class IDs via environment variables:
- `BIRD_CLASS_ID=1` (for custom model)
- `HUMAN_CLASS_ID=0` (for custom model)
- `SQUIRREL_CLASS_ID=2` (for custom model)

The service will also auto-detect class IDs from the model's class names if not explicitly set.

**Status**: ✅ Fixed in `docker-compose.yml` - class IDs are now correctly set for the custom model.

### 2. Confidence Threshold Too High

**Check**: Current bird confidence threshold is set to `0.1` (10%), which is very low. If birds still aren't detected, the model might not be recognizing them at all.

**Debugging**:
- Enable debug mode: `DETECTION_DEBUG=true` and `DETECTION_DEBUG_SAVE=true`
- Check detection service logs for confidence scores
- Look at debug images in `data/images/debug/` to see what the model is detecting

**Adjustment**: Lower the threshold even more (e.g., `0.05`) or check if the model needs retraining.

### 3. Motion Detection Not Triggering

**Check**: If images aren't being captured at all, motion detection might not be working.

**Debugging**:
- Check capture service logs for motion detection messages
- Verify camera is working: `curl http://localhost:8080/capture/live`
- Check motion detection settings:
  - `MOTION_MIN_AREA=3000` (lower = more sensitive)
  - `MOTION_MOG2_VAR_THRESHOLD=35` (lower = more sensitive)
  - `MOTION_BINARY_THRESHOLD=175` (lower = more sensitive)

**Adjustment**: Lower these values to make motion detection more sensitive.

### 4. Model Performance Issues

**Check**: The model might not be trained well enough for your specific feeder setup.

**Debugging**:
- Check model training metrics in `models/yolov8_person_bird_squirrel/20251113_085413/results.csv`
- Look at training images: `models/yolov8_person_bird_squirrel/20251113_085413/train_batch*.jpg`
- Review validation results

**Solutions**:
- Retrain with more bird images from your specific camera/feeder
- Include images with similar lighting conditions
- Increase training epochs
- Use data augmentation

### 5. Image Quality Issues

**Check**: Poor image quality can affect detection.

**Debugging**:
- Check captured images in `data/images/`
- Verify camera resolution and quality settings
- Check for motion blur (increase `MOTION_DELAY` if needed)

**Adjustment**:
- Increase `JPEG_QUALITY=95` (already high)
- Increase `MOTION_DELAY=1.5` to allow motion to settle before capture
- Check camera focus and positioning

### 6. Service Not Processing Images

**Check**: Verify the full pipeline is working.

**Debugging**:
1. Check capture service logs - should see "Published to Redis queue"
2. Check detection service logs - should see "Processing frames..." and detection results
3. Check storage service logs - should see "✓ Stored detection"
4. Check API - visit `http://localhost:8000` to see detections

**Verification**:
```bash
# Check if services are running
docker ps

# Check detection service logs
docker logs bird-monitor-detection

# Check capture service logs
docker logs bird-monitor-capture

# Check recent detections in database
docker exec -it bird-monitor-db psql -U birdmonitor -d birdmonitor -c "SELECT id, timestamp, is_bird, confidence FROM detections ORDER BY timestamp DESC LIMIT 10;"
```

### 7. Recent Changes

After fixing the class ID issue, restart the detection service:

```bash
docker-compose restart detection-service
```

Or restart all services:

```bash
docker-compose restart
```

### Next Steps

1. ✅ **Fixed**: Class ID mismatch - restart detection service
2. Monitor logs for a few minutes after restart
3. Check debug images if enabled
4. If still not detecting, lower confidence threshold further
5. If model confidence is consistently low, consider retraining with more feeder-specific images

