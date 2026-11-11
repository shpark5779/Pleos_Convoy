package com.example.pleosprojectv01

import android.Manifest
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.skt.tmap.engine.navigation.route.RoutePlanType
import com.skt.tmap.engine.navigation.SDKManager
import com.skt.tmap.vsm.data.VSMMapPoint
import com.skt.tmap.vsm.map.marker.MarkerImage
import com.skt.tmap.vsm.map.marker.VSMMarkerPoint
import com.skt.tmap.engine.navigation.network.ndds.NddsDataType.DestSearchFlag
import com.skt.tmap.engine.navigation.network.ndds.CarOilType
import com.skt.tmap.engine.navigation.network.ndds.TollCarType
import com.skt.tmap.engine.navigation.route.data.MapPoint
import com.skt.tmap.engine.navigation.route.data.WayPoint
import com.tmapmobility.tmap.tmapsdk.ui.fragment.NavigationFragment
import com.tmapmobility.tmap.tmapsdk.ui.util.TmapUISDK
import com.tmapmobility.tmap.tmapsdk.ui.data.DrivingStartCallback
import com.tmapmobility.tmap.tmapsdk.ui.data.CarOption
import com.tmapmobility.tmap.tmapsdk.ui.data.NavigationScreenState
import com.tmapmobility.tmap.tmapsdk.ui.data.NavigationScreenStateListener
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors

/** Official TMAP UI SDK. Its initialization and route results stay separate from REST results. */
class NativeTmapActivity : AppCompatActivity() {
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private val prefs by lazy { getSharedPreferences("convoy", MODE_PRIVATE) }
    private val resultPrefs by lazy { getSharedPreferences("native_tmap_result", MODE_PRIVATE) }
    private lateinit var status: TextView
    private lateinit var location: PleosLocation
    private var navigation: NavigationFragment? = null
    private var currentLocation: JSONObject? = null
    private var authorized = false
    private var initializing = false
    private var requesting = false
    private var simulation = false
    private var simulationStarted = false
    private var startingSimulation = false
    private var activeSession: ConvoySession? = null
    private var finalDestination = ""
    private var lastTelemetry = 0L
    private lateinit var planControls: ConvoyPlanControls
    private var routeEnabled=false
    private var attemptedPlanVersion=-1
    private var requestedPlanVersion=-1
    private lateinit var companionsStatus: TextView
    private var visible = false
    private var pollingCompanions = false
    private val companionMarkerIds = mutableSetOf<String>()
    private val companionIcon by lazy {
        val bitmap = Bitmap.createBitmap(96,96,Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(132,45,196) }
        canvas.drawCircle(48f,48f,45f,paint)
        paint.color = Color.WHITE
        canvas.drawRoundRect(27f,20f,69f,76f,10f,10f,paint)
        paint.color = Color.rgb(132,45,196)
        canvas.drawRect(33f,31f,63f,46f,paint)
        canvas.drawRect(33f,59f,63f,66f,paint)
        MarkerImage.fromBitmap(bitmap)
    }
    private val companionTick = object : Runnable {
        override fun run() {
            if (!visible) return
            pollCompanions()
            main.postDelayed(this,3000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        resultPrefs.edit().clear().apply()
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        status = TextView(this).apply { textSize = 18f; setPadding(20, 10, 20, 10) }
        column.addView(status)
        companionsStatus = TextView(this).apply { text = "동행 차량 위치 수신 대기 · 보라색 자동차"; textSize = 17f }
        column.addView(companionsStatus)
        planControls=ConvoyPlanControls(this);column.addView(planControls)
        val controls = LinearLayout(this)
        fun control(text: String, action: () -> Unit) {
            controls.addView(Button(this).apply { this.text=text; isAllCaps=false; minHeight=64
                setOnClickListener { action() } }, LinearLayout.LayoutParams(0,-2,1f))
        }
        control("SDK 인증 확인") { initializeSdk() }
        control("승인 계획 · 실제 안내") { requestRoute(false) }
        control("승인 계획 · SDK 모의주행") { requestRoute(true) }
        control("닫기") { finish() }
        column.addView(controls)
        column.addView(FrameLayout(this).apply { id=R.id.native_tmap_container }, LinearLayout.LayoutParams(-1,0,1f))
        setContentView(column)
        location = PleosLocation(this, { p ->
            main.post { currentLocation=JSONObject().put("latitude",p.latitude).put("longitude",p.longitude)
                .put("measured_at",p.timestampMillis/1000.0) }
        }, { })
        phase("CONFIGURED", "정식 TMAP Navi SDK 1.78 · ClientID ${if(BuildConfig.TMAP_CLIENT_ID.isBlank()) "미설정" else "설정됨"}")
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED) initializeSdk()
        else requestPermissions(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION),18)
    }

    override fun onStart() {
        super.onStart()
        visible=true; main.post(companionTick)
        if(checkSelfPermission("pleos.car.permission.FUSED_LOCATION")==PackageManager.PERMISSION_GRANTED) location.start()
    }
    override fun onStop() { visible=false; main.removeCallbacks(companionTick); clearCompanions(); location.stop(); currentLocation=null; super.onStop() }
    override fun onDestroy() {
        location.stop()
        planControls.close()
        runCatching { navigation?.stopDrive(); if(authorized) TmapUISDK.finish() }
        io.shutdown(); super.onDestroy()
    }
    override fun onRequestPermissionsResult(code:Int,permissions:Array<out String>,results:IntArray) {
        super.onRequestPermissionsResult(code,permissions,results)
        if(code==18 && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED) initializeSdk()
        else if(code==18) phase("PERMISSION_REQUIRED","정식 내비 SDK에 Android 위치 권한이 필요합니다.")
    }

    private fun safe(value:String?):String {
        var text=value.orEmpty()
        for(secret in listOf(BuildConfig.TMAP_NATIVE_APP_KEY,BuildConfig.TMAP_CLIENT_ID).filter { it.isNotEmpty() }) text=text.replace(secret,"[REDACTED]")
        return text.take(300)
    }
    private fun phase(state:String,message:String) {
        main.post {
            if(!isDestroyed) status.text=message
            resultPrefs.edit().putString("phase",state).putString("detail",safe(message))
                .putLong("updated_at",System.currentTimeMillis()).apply()
            Log.i("NativeTmapCheck",state) // No app keys, URLs or provider request bodies.
        }
    }
    private fun routeFailed(code:Int,message:String?) {
        requesting=false
        resultPrefs.edit().putInt("error_code",code).apply()
        val detail=if(code==429) {
            "TMAP 경로 요청 제한(429). SK Open API 대시보드에서 내비게이션 사용량·한도를 확인한 뒤 다시 시도해 주세요."
        } else "정식 SDK 경로 요청 실패 ($code): ${safe(message)}"
        phase("ROUTE_FAILED",detail)
    }
    private fun installationId():String = prefs.getString("tmap_device_id",null) ?: UUID.randomUUID().toString().also {
        prefs.edit().putString("tmap_device_id",it).apply()
    }

    private fun clearCompanions() {
        val manager=navigation?.getMapView()?.markerManager
        companionMarkerIds.forEach { manager?.removeMarker(it) }
        companionMarkerIds.clear()
    }

    private fun pollCompanions() {
        if (!authorized || pollingCompanions) return
        val code=prefs.getString("code","").orEmpty()
        if (code.isEmpty()) { companionsStatus.text="동행 차량을 보려면 모임에 참가하세요."; return }
        val session=ConvoySession(prefs.getString("server","http://10.0.2.2:8765")!!,code,
            prefs.getString("member_id","")!!,prefs.getString("token","")!!)
        val own=if (simulationStarted) null else currentLocation?.takeIf {
            System.currentTimeMillis()/1000.0-it.optDouble("measured_at") in -5.0..30.0
        }?.let { JSONObject(it.toString()).put("source","sdk") }
        pollingCompanions=true
        io.execute {
            val result=runCatching { if(own==null) ConvoyApi.room(session) else ConvoyApi.room(session,"location",own) }
            main.post {
                pollingCompanions=false
                if (!visible) return@post
                result.onSuccess { room ->
                    planControls.update(room)
                    if(routeEnabled && !requesting && room.optInt("plan_version")>attemptedPlanVersion) requestRoute(false)
                    val manager=navigation?.getMapView()?.markerManager ?: return@onSuccess
                    val vehicles=companionVehicles(room,session.memberId,System.currentTimeMillis()/1000.0)
                    clearCompanions()
                    vehicles.forEach { vehicle ->
                        val id="convoy-${vehicle.id}"
                        val marker=VSMMarkerPoint(id).apply {
                            icon=companionIcon; text="동행 · ${vehicle.name}"
                            position=VSMMapPoint(vehicle.longitude,vehicle.latitude)
                        }
                        manager.addMarker(marker); companionMarkerIds.add(id)
                    }
                    companionsStatus.text="동행 차량 ${vehicles.size}대 · 보라색 자동차 · 3초 간격 갱신"
                    resultPrefs.edit().putInt("companion_count",vehicles.size)
                        .putString("companion_positions",vehicles.joinToString { "${it.id}:${it.latitude},${it.longitude}" })
                        .putLong("companions_updated_at",System.currentTimeMillis()).apply()
                }.onFailure {
                    clearCompanions()
                    companionsStatus.text="동행 위치 수신 실패 · 서버 연결을 확인하세요."
                    resultPrefs.edit().putInt("companion_count",0).apply()
                }
            }
        }
    }

    private fun initializeSdk() {
        if(initializing || authorized) return
        if(BuildConfig.TMAP_NATIVE_APP_KEY.isBlank()) { phase("KEY_REQUIRED",".env의 TMAP_APP_KEY 설정 후 앱을 다시 빌드하세요.");return }
        if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED) {
            phase("PERMISSION_REQUIRED","Android 위치 권한이 필요합니다.");return
        }
        initializing=true
        phase("INITIALIZING","정식 SDK 라이브러리·인증 확인 중${if(BuildConfig.TMAP_CLIENT_ID.isBlank()) " · ClientID 미설정" else ""}")
        try {
            if(navigation==null) {
                navigation=(supportFragmentManager.findFragmentById(R.id.native_tmap_container) as? NavigationFragment)
                    ?: TmapUISDK.getFragment().also {
                        supportFragmentManager.beginTransaction().replace(R.id.native_tmap_container,it).commitNow()
                    }
                observeDriving()
            }
            TmapUISDK.initialize(this,BuildConfig.TMAP_CLIENT_ID,BuildConfig.TMAP_NATIVE_APP_KEY,
                "",installationId(),object:TmapUISDK.InitializeListener {
                    override fun onSuccess() {
                        initializing=false;authorized=true
                        phase("SDK_READY","정식 SDK 초기화 성공 · 모임에서 승인된 목적지·경유지로 안내를 요청할 수 있습니다.")
                    }
                    override fun onFail(errorCode:Int,errorMsg:String?) {
                        initializing=false;authorized=false
                        resultPrefs.edit().putInt("error_code",errorCode).apply()
                        phase("SDK_AUTH_FAILED","정식 SDK 초기화 실패 ($errorCode): ${safe(errorMsg)}\nClientID와 내비 SDK 이용 권한·한도를 확인하세요.")
                    }
                    override fun savedRouteInfoExists(destinationName:String?) {
                        resultPrefs.edit().putBoolean("saved_route_exists",true).apply()
                        main.post { navigation?.clearContinueDriveInfo() }
                        phase(if(authorized) "SDK_READY" else "SAVED_ROUTE_EXISTS","이전 SDK 경로가 있습니다. 승인된 현재 계획으로 새로 요청하세요.")
                    }
                },null)
        } catch(error:LinkageError) {
            initializing=false;phase("SDK_LIBRARY_FAILED","SDK 네이티브 라이브러리 로드 실패: ${safe(error.message)}")
        } catch(error:Exception) {
            initializing=false;phase("SDK_INITIALIZE_FAILED","SDK 초기화 오류: ${safe(error.message)}")
        }
    }

    private fun observeDriving() {
        navigation!!.setNavigationScreenStateListener(object:NavigationScreenStateListener {
            override fun onChanged(state:NavigationScreenState) {
                if(state is NavigationScreenState.SimulationScreen) {
                    simulationStarted=true;phase("SIMULATION_RUNNING","정식 SDK 내부 모의주행 중")
                } else if(state is NavigationScreenState.SelectRouteScreen) {
                    phase("ROUTE_PREVIEW","정식 SDK 경로 미리보기 · SDK에서 경로를 선택하세요.")
                    if(simulation)main.postDelayed({ startSdkSimulation() },500)
                }
            }
        })
        navigation!!.drivingStatusCallback=object:TmapUISDK.DrivingStatusCallback {
            override fun onStartNavigation() { phase(if(simulationStarted) "SIMULATION_RUNNING" else "NAVIGATION_RUNNING",if(simulationStarted) "정식 SDK 모의주행 중" else "정식 SDK 길안내 중") }
            override fun onStartNavigationInfo(totalDistanceInMeter:Int,totalTimeInSec:Int,tollFee:Int) {
                requesting=false
                resultPrefs.edit().putInt("distance_m",totalDistanceInMeter).putInt("duration_s",totalTimeInSec)
                    .putInt("sdk_plan_version",requestedPlanVersion).apply()
                phase(if(simulationStarted) "SIMULATION_RUNNING" else "NAVIGATION_RUNNING","정식 SDK 안내 중 · 반영 계획 v$requestedPlanVersion")
            }
            override fun onStopNavigation() { requesting=false
                if(resultPrefs.getBoolean("arrived_final",false))phase("ARRIVED","정식 SDK 목적지 도착 완료")
                else phase("SDK_STOPPED","정식 SDK 주행 종료")
            }
            override fun onTryToStopNavigation()=false
            override fun onArrivedDestination(destination:String,drivingTime:Int,drivingDistance:Int) {
                val finished=destination==finalDestination
                requesting=false
                resultPrefs.edit().putInt("driving_time",drivingTime).putInt("driving_distance",drivingDistance)
                    .putString("arrived_destination",destination).putBoolean("arrived_final",finished).apply()
                phase(if(finished) "ARRIVED" else "WAYPOINT_ARRIVED", "정식 SDK 도착 이벤트: $destination")
            }
            override fun onLocationChanged() {
                val session=activeSession ?: return
                val now=System.currentTimeMillis();if(now-lastTelemetry<2000)return;lastTelemetry=now
                SDKManager.getInstance().requestCurrentLocation { p ->
                    val data=JSONObject().put("latitude",p.latitude).put("longitude",p.longitude)
                        .put("measured_at",System.currentTimeMillis()/1000.0).put("source",if(simulationStarted) "demo" else "sdk")
                    resultPrefs.edit().putString("sdk_latitude",p.latitude.toString()).putString("sdk_longitude",p.longitude.toString()).apply()
                    if(!io.isShutdown)io.execute { runCatching { ConvoyApi.room(session,"location",data) } }
                }
            }
            override fun onPermissionDenied(errorCode:Int,errorMsg:String?) { phase("SDK_PERMISSION_DENIED",safe(errorMsg)) }
            override fun onFailRouteRequest(errorCode:String,errorMessage:String) { routeFailed(errorCode.toIntOrNull() ?: -1,errorMessage) }
            override fun onPassedViaPoint() { resultPrefs.edit().putBoolean("via_passed",true).apply() }
            override fun onApproachingViaPoint() {}
            override fun onRouteChanged(index:Int) {}
            override fun onRouteOptionChanged(originalOption:RoutePlanType,changedOption:RoutePlanType) {}
            override fun onPeriodicRerouteComplete() {}
            override fun onPeriodicReroute() {}
            override fun onPassedTollgate(fee:Int) {}
            override fun onPassedAlternativeRouteJunction() {}
            override fun onNoLocationSignal(noLocationSignal:Boolean) { resultPrefs.edit().putBoolean("no_location_signal",noLocationSignal).apply() }
            override fun onDoNotRerouteToDestinationComplete() {}
            override fun onDestinationDirResearchComplete() {}
            override fun onChangeRouteOptionComplete(routePlanType:RoutePlanType) {}
            override fun onBreakawayFromRouteEvent() { phase("OFF_ROUTE","정식 SDK 경로 이탈 감지") }
            override fun onBreakAwayRequestComplete() {}
            override fun onApproachingAlternativeRoute() {}
            override fun onForceReroute(periodicType:DestSearchFlag) {}
            override fun onUserRerouteComplete() {}
        }
    }

    private fun startSdkSimulation() {
        if(!simulation || startingSimulation || simulationStarted)return
        val result=TmapUISDK.getRouteResult() ?: return
        startingSimulation=true
        phase("SIMULATION_STARTING","정식 SDK의 계산된 경로로 모의주행 시작 중")
        navigation!!.startDrivingForJava(0,result,true,object:DrivingStartCallback {
            override fun onSuccess() { startingSimulation=false;simulationStarted=true;phase("SIMULATION_RUNNING","정식 SDK 내부 모의주행 중") }
            override fun onError(throwable:Throwable) { startingSimulation=false;requesting=false;phase("START_FAILED",safe(throwable.message)) }
        })
    }

    private fun requestRoute(simulation:Boolean) {
        if(!authorized) { phase("AUTH_REQUIRED","SDK 인증이 완료되어야 경로 요청·모의주행이 가능합니다.");return }
        if(requesting)return
        routeEnabled=true
        val code=prefs.getString("code","").orEmpty()
        if(code.isEmpty()) { phase("ROOM_REQUIRED","먼저 동행 모임에 참가하세요.");return }
        val session=ConvoySession(prefs.getString("server","http://10.0.2.2:8765")!!,code,
            prefs.getString("member_id","")!!,prefs.getString("token","")!!)
        requesting=true
        this.simulation=simulation;simulationStarted=false;startingSimulation=false;activeSession=session
        resultPrefs.edit().putBoolean("arrived_final",false).putBoolean("via_passed",false).putInt("error_code",0).apply()
        phase("PLAN_LOADING","현재 승인된 동행 이동 계획 확인 중")
        io.execute {
            val response=runCatching { ConvoyApi.room(session) }
            main.post {
                if(isDestroyed)return@post
                response.onSuccess { room ->
                    runCatching {
                        val member=room.getJSONObject("members").getJSONObject(session.memberId)
                        check(member.optString("role","driver")=="driver") { "운전자만 경로를 요청할 수 있습니다." }
                        val point=currentLocation ?: member.optJSONObject("location")
                        check(point!=null && System.currentTimeMillis()/1000.0-point.getDouble("measured_at") in -5.0..30.0) { "최근 차량 위치가 필요합니다. 실제 위치 공유를 켜 주세요." }
                        fun waypoint(p:JSONObject)=WayPoint(p.optString("name","현재 위치"),MapPoint(p.getDouble("longitude"),p.getDouble("latitude")))
                        val vias=room.getJSONArray("waypoints")
                        val pass=ArrayList<WayPoint>();for(i in 0 until vias.length())pass.add(waypoint(vias.getJSONObject(i)))
                        resultPrefs.edit().putInt("plan_version",room.getInt("plan_version"))
                            .putBoolean("simulation",simulation).putInt("waypoint_count",pass.size).apply()
                        phase("ROUTE_REQUESTED",if(simulation) "정식 SDK 모의주행 경로 요청 중" else "정식 SDK 실제 안내 경로 요청 중")
                        finalDestination=room.getJSONObject("destination").getString("name")
                        requestedPlanVersion=room.getInt("plan_version");attemptedPlanVersion=requestedPlanVersion
                        resultPrefs.edit().putInt("sdk_requested_plan_version",requestedPlanVersion).apply()
                        navigation!!.carOption=CarOption().apply {
                            carType=TollCarType.Car;oilType=CarOilType.Gasoline;isHipassOn=true
                        }
                        resultPrefs.edit().putString("request_origin_latitude",point!!.getDouble("latitude").toString())
                            .putString("request_origin_longitude",point.getDouble("longitude").toString()).apply()
                        // SDK argument is withoutPreview; simulation starts separately with startDrivingForJava.
                        navigation!!.requestRoute(waypoint(point!!),pass,waypoint(room.getJSONObject("destination")),!simulation,
                            object:TmapUISDK.RouteRequestListener {
                                override fun onSuccess() {
                                    requesting=false
                                    resultPrefs.edit().putInt("sdk_plan_version",requestedPlanVersion).apply()
                                    phase("ROUTE_READY","정식 SDK 경로 계산 완료")
                                    if(simulation)main.post { startSdkSimulation() }
                                }
                                override fun onFail(errorCode:Int,errorMsg:String?) {
                                    routeFailed(errorCode,errorMsg)
                                }
                            },arrayListOf(RoutePlanType.Traffic_Recommend))
                    }.onFailure { requesting=false;phase("PLAN_FAILED",safe(it.message)) }
                }.onFailure { requesting=false;phase("PLAN_FAILED",safe(it.message)) }
            }
        }
    }
}

internal data class CompanionVehicle(val id:String,val name:String,val latitude:Double,val longitude:Double)

/** Ignore own car, passengers, invalid coordinates and locations older than 30 seconds. */
internal fun companionVehicles(room:JSONObject,ownId:String,now:Double):List<CompanionVehicle> {
    val members=room.optJSONObject("members") ?: return emptyList()
    return members.keys().asSequence().filter { it!=ownId }.mapNotNull { id ->
        val member=members.optJSONObject(id) ?: return@mapNotNull null
        if (member.optString("role","driver")!="driver") return@mapNotNull null
        val point=member.optJSONObject("location") ?: return@mapNotNull null
        val lat=point.optDouble("latitude"); val lon=point.optDouble("longitude")
        val age=now-point.optDouble("measured_at")
        if (lat !in -90.0..90.0 || lon !in -180.0..180.0 || age !in -5.0..30.0) return@mapNotNull null
        CompanionVehicle(id,member.optString("name","동행 차량").take(30),lat,lon)
    }.toList()
}
