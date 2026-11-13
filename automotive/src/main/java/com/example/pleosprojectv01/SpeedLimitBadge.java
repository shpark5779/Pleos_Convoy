package com.example.pleosprojectv01;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.location.Location;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import java.util.List;

/** App-drawn road limit, sourced from the official SDK. Not the SDK's camera/SDI sign. */
public final class SpeedLimitBadge extends View {
    private static final String TAG="convoy-road-speed-limit";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private Integer limit;
    private float speed;
    private final Runnable tick=new Runnable() {
        @Override public void run() {
            refresh();handler.postDelayed(this,700);
        }
    };
    public SpeedLimitBadge(Activity activity) { super(activity);setTag(TAG); }

    public static void attach(Activity activity) {
        FrameLayout content=activity.findViewById(android.R.id.content);
        if(content.findViewWithTag(TAG)!=null)return;
        SpeedLimitBadge badge=new SpeedLimitBadge(activity);
        float density=activity.getResources().getDisplayMetrics().density;
        FrameLayout.LayoutParams params=new FrameLayout.LayoutParams((int)(130*density),(int)(166*density),Gravity.TOP|Gravity.END);
        params.topMargin=(int)(content.getHeight()*.25f);params.rightMargin=(int)(18*density);
        content.addView(badge,params);
    }
    @Override protected void onAttachedToWindow() { super.onAttachedToWindow();handler.post(tick); }
    @Override protected void onDetachedFromWindow() { handler.removeCallbacks(tick);super.onDetachedFromWindow(); }

    private static Object call(Object object,String name) throws Exception {
        return object.getClass().getMethod(name).invoke(object);
    }
    private void refresh() {
        try {
            // Public getters keep this view independent of the SDK's obfuscated backing fields.
            Class<?> sdk=Class.forName("com.tmapmobility.tmap.tmapsdk.ui.util.TmapUISDK");
            Object live=sdk.getField("observableRouteData").get(null);
            Object data=call(live,"getValue");
            Class<?> managerClass=Class.forName("com.skt.tmap.engine.navigation.SDKManager");
            Object companion=managerClass.getField("Companion").get(null);
            Object manager=call(companion,"getInstance");
            Location location=(Location)call(manager,"getCurrentPosition");
            if(data==null || location==null)throw new IllegalStateException("No SDK route/location");
            List<?> coordinates=(List<?>)call(data,"getRouteCoordinates");
            List<?> roads=(List<?>)call(data,"getRoadInfos");
            double[][] points=new double[coordinates.size()][2];
            for(int i=0;i<points.length;i++) {
                points[i][0]=((Number)call(coordinates.get(i),"getLongitude")).doubleValue();
                points[i][1]=((Number)call(coordinates.get(i),"getLatitude")).doubleValue();
            }
            int[][] sections=new int[roads.size()][3];
            for(int i=0;i<sections.length;i++) {
                Object road=roads.get(i);
                sections[i][0]=((Number)call(road,"getStartVtxIndex")).intValue();
                sections[i][1]=((Number)call(road,"getEndVtxIndex")).intValue();
                sections[i][2]=((Number)call(road,"getMaxSpeedKmh")).intValue();
            }
            limit=resolve(points,sections,location.getLatitude(),location.getLongitude());
            speed=location.hasSpeed()?location.getSpeed()*3.6f:0;
        } catch(Exception ignored) { limit=null;speed=0; }
        setContentDescription("SDK 도로 제한속도 "+(limit==null?"미확인":limit+" km/h")+" · 현재 "+Math.round(speed)+" km/h");
        invalidate();
    }

    public static Integer resolve(double[][] points,int[][] roads,double latitude,double longitude) {
        if(!Double.isFinite(latitude)||!Double.isFinite(longitude)||points.length<2)return null;
        double nearest=Double.POSITIVE_INFINITY;int edge=-1;
        double scale=Math.cos(Math.toRadians(latitude));
        for(int i=0;i<points.length-1;i++) {
            double ax=(points[i][0]-longitude)*scale,ay=points[i][1]-latitude;
            double dx=(points[i+1][0]-points[i][0])*scale,dy=points[i+1][1]-points[i][1];
            double squared=dx*dx+dy*dy;if(squared==0)continue;
            double t=Math.max(0,Math.min(1,-(ax*dx+ay*dy)/squared));
            double distance=Math.hypot(ax+t*dx,ay+t*dy)*111195;
            if(distance<=nearest+1e-7) { nearest=distance;edge=i; }
        }
        if(nearest>80||edge<0)return null;
        Integer value=null;
        for(int[] road:roads) {
            if(road[0]<=edge && edge<=road[1]) {
                if(road[2]<=0||road[2]>240)return null;
                value=value==null?road[2]:Math.min(value,road[2]);
            }
        }
        return value;
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float unit=getWidth()/130f;canvas.save();canvas.scale(unit,unit);
        paint.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));paint.setTextAlign(Paint.Align.CENTER);
        paint.setStyle(Paint.Style.FILL);paint.setColor(Color.WHITE);
        canvas.drawRoundRect(0,0,130,166,12,12,paint);
        paint.setColor(Color.rgb(35,45,55));paint.setTextSize(14);canvas.drawText("도로 제한",65,20,paint);
        paint.setColor(Color.rgb(210,20,35));paint.setStrokeWidth(7);paint.setStyle(Paint.Style.STROKE);
        canvas.drawCircle(65,76,44,paint);
        paint.setStyle(Paint.Style.FILL);paint.setColor(Color.BLACK);paint.setTextSize(limit!=null&&limit>=100?37:46);
        canvas.drawText(limit==null?"—":limit.toString(),65,92,paint);
        paint.setColor(limit!=null&&speed>limit+.5?Color.RED:Color.DKGRAY);paint.setTextSize(13);
        canvas.drawText("현재 "+Math.round(speed)+" km/h",65,140,paint);
        paint.setColor(Color.GRAY);paint.setTextSize(11);canvas.drawText(limit==null?"제한속도 미확인":"SDK 도로정보",65,158,paint);
        canvas.restore();
    }
}
