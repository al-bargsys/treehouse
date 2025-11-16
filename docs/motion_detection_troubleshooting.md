# Motion Detection Troubleshooting

## Issue: Motion Detection Not Triggering

If you're moving around in front of the camera but seeing "0 motion events", here's how to troubleshoot:

### Current Settings (After Fix)

- `MOTION_MIN_AREA=1000` (lowered from 3000 - more sensitive)
- `MOTION_MOG2_VAR_THRESHOLD=25` (lowered from 35 - more sensitive)
- `MOTION_BINARY_THRESHOLD=150` (lowered from 175 - more sensitive)
- `MOTION_DEBUG=true` (enabled for diagnostics)

### Common Issues

#### 1. Service Not Restarted

**Problem**: Changes to `docker-compose.yml` require a service restart.

**Solution**:
```bash
docker-compose restart capture-service
```

Or rebuild and restart:
```bash
docker-compose up -d --build capture-service
```

#### 2. Warmup Period

**Problem**: MOG2 background subtractor needs ~5 seconds (75 frames at 15fps) to learn the background before motion detection starts.

**Check**: Look for "✓ Background model warmed up" in logs.

**Solution**: Wait for warmup to complete, or reduce warmup time in code if needed.

#### 3. Camera Movement

**Problem**: When you physically move the camera, the entire scene changes. MOG2 will adapt to the new scene as background, which can temporarily disable motion detection.

**Solution**: 
- Keep camera stationary
- If you must move it, wait 5-10 seconds for MOG2 to learn the new background
- Consider using a tripod or fixed mount

#### 4. Thresholds Too High

**Problem**: Motion area detected is below the minimum threshold.

**Diagnosis**: Check status endpoint or logs:
```bash
# Check status
curl http://localhost:8080/capture/status

# Or check logs
docker logs bird-monitor-capture --tail 20 | grep "Motion detection"
```

**Solution**: Lower thresholds further:
- `MOTION_MIN_AREA=500` (even more sensitive)
- `MOTION_MOG2_VAR_THRESHOLD=20` (even more sensitive)
- `MOTION_BINARY_THRESHOLD=120` (even more sensitive)

#### 5. Low Light Conditions

**Problem**: Motion detection is less effective in low light.

**Check**: Look for `low_light: true` in status endpoint.

**Solution**: Improve lighting or adjust camera settings.

### Debugging Steps

1. **Check if service is running**:
   ```bash
   docker ps | grep capture
   ```

2. **Check current settings**:
   ```bash
   docker exec bird-monitor-capture printenv | grep MOTION_
   ```

3. **Check status endpoint** (if accessible):
   ```bash
   curl http://localhost:8080/capture/status | python3 -m json.tool
   ```
   
   Look for:
   - `motion_area`: Current detected motion area
   - `motion_min_area`: Threshold that must be exceeded
   - `motion_detected`: Whether motion is currently detected

4. **Check logs for motion debug info**:
   ```bash
   docker logs bird-monitor-capture --tail 50 | grep -E "(Motion|Status)"
   ```

5. **Use diagnostic script**:
   ```bash
   ./scripts/check_motion_detection.sh
   ```

### Understanding Motion Detection

The system uses MOG2 (Mixture of Gaussians) background subtraction:

1. **Warmup**: First ~5 seconds, MOG2 learns the static background
2. **Detection**: After warmup, compares each frame to learned background
3. **Thresholds**:
   - `MOTION_MOG2_VAR_THRESHOLD`: How different a pixel must be to be considered foreground (lower = more sensitive)
   - `MOTION_BINARY_THRESHOLD`: Threshold for binary mask (lower = more sensitive)
   - `MOTION_MIN_AREA`: Minimum number of pixels with motion to trigger capture (lower = more sensitive)

### Quick Fixes

**Make motion detection more sensitive**:
```yaml
# In docker-compose.yml
- MOTION_MIN_AREA=500
- MOTION_MOG2_VAR_THRESHOLD=20
- MOTION_BINARY_THRESHOLD=120
```

Then restart:
```bash
docker-compose restart capture-service
```

**Check if it's working**:
```bash
# Watch logs in real-time
docker logs -f bird-monitor-capture | grep -E "(Motion|Status)"
```

Move around in front of the camera and you should see motion detection values increase.

