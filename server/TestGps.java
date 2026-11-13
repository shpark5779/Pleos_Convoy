import android.content.Context;
import android.location.Location;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Looper;
import android.os.SystemClock;

/** Shell-only emulator test GPS update; does not interact with the navigation API. */
public class TestGps {
    public static void main(String[] args) throws Exception {
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Object thread = threadClass.getMethod("systemMain").invoke(null);
        Context context = (Context)threadClass.getMethod("getSystemContext").invoke(thread);
        LocationManager manager = (LocationManager)context.getSystemService(Context.LOCATION_SERVICE);
        Location point = new Location("gps");
        point.setLatitude(Double.parseDouble(args[0]));
        point.setLongitude(Double.parseDouble(args[1]));
        point.setSpeed(Float.parseFloat(args[2]));
        point.setBearing(Float.parseFloat(args[3]));
        point.setAccuracy(5f); point.setAltitude(0);
        point.setSpeedAccuracyMetersPerSecond(.5f);point.setBearingAccuracyDegrees(5f);
        point.setTime(System.currentTimeMillis());point.setElapsedRealtimeNanos(SystemClock.elapsedRealtimeNanos());
        Bundle extras = new Bundle(); extras.putInt("satellites",8);point.setExtras(extras);
        manager.setTestProviderLocation("gps",point);
        System.out.println("Test GPS updated");
        System.exit(0);
    }
}
