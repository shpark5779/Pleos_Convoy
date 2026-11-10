package com.example.pleosprojectv01

import android.content.Context
import android.os.Handler
import android.os.Looper
import ai.pleos.playground.location.fused.FusedLocation
import ai.pleos.playground.location.fused.listener.FusedLocationListener
import ai.pleos.playground.location.fused.model.LocationData
import ai.pleos.playground.navi.constants.NaviErrorCode
import ai.pleos.playground.navi.constants.WaypointIndex
import ai.pleos.playground.navi.data.DestinationInfo
import ai.pleos.playground.navi.data.RequestWaypointInfo
import ai.pleos.playground.navi.data.RouteInfo
import ai.pleos.playground.navi.data.RouteWithWaypointsRequest
import ai.pleos.playground.navi.data.WaypointInfo
import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import org.json.JSONObject
import kotlin.math.abs

class PleosLocation(context: Context, private val onLocation: (LocationData) -> Unit, private val onStatus: (String) -> Unit) {
    private val sdk = FusedLocation(context.applicationContext)
    private var started = false
    private val listener = object : FusedLocationListener {
        override fun onChanged(location: LocationData?) {
            if (started && location != null) onLocation(location)
            else if (started) onStatus("SDK 위치가 아직 없습니다.")
        }
        override fun onError(exception: Exception) { if (started) onStatus("위치 오류: ${exception.message}") }
    }

    fun start() {
        if (started) return
        runCatching {
            check(sdk.isSupported()) { "이 기기는 Pleos 위치 서비스를 지원하지 않습니다." }
            started = true
            sdk.initialize()
            sdk.registerFusedLocationCallback(listener)
            sdk.getLastKnownLocation(listener)
            onStatus("실제 SDK 위치 수신 중")
        }.onFailure { stop(); onStatus(it.message ?: "위치 연결 실패") }
    }

    fun stop() {
        if (started) {
            started = false
            runCatching { sdk.unregisterFusedLocationCallback(listener) }
            runCatching { sdk.release() }
        }
    }
}

class PleosNavigation(context: Context, private val onStatus: (String) -> Unit) {
    private val main = Handler(Looper.getMainLooper())
    private val sdk = NaviHelper(context.applicationContext)
    private var connected = false
    private var closed = false
    private var destination: JSONObject? = null
    private var waypoint: JSONObject? = null
    private var completed = false
    private var destinationMatches = false
    private var waypointMatches = false
    private var onResult: ((String, String) -> Unit)? = null
    private val timeout = Runnable { finish("unconfirmed", "내비 응답을 확인하지 못했습니다. 실제 내비 화면을 확인하세요.") }

    private fun matches(place: JSONObject?, lat: Double, lon: Double): Boolean = place != null &&
        abs(place.getDouble("latitude") - lat) < 0.001 && abs(place.getDouble("longitude") - lon) < 0.001

    private val listener = object : NaviHelperEventListener {
        override fun onRoutingCompleted() { main.post {
            if (onResult != null) {
                completed = true
                runCatching { sdk.getDestinationInfo(); sdk.getWaypointInfo() }
                    .onFailure { finish("unconfirmed", "경로 조회 권한 또는 서비스 오류: ${it.message}") }
            }
        } }
        override fun onDestinationInfo(destinationInfo: DestinationInfo) { main.post {
            if (completed) {
                destinationMatches = matches(destination, destinationInfo.latitude, destinationInfo.longitude)
                verify()
            }
        } }
        override fun onWayPointInfo(waypointInfoList: List<WaypointInfo>) { main.post {
            if (completed) {
                waypointMatches = waypointInfoList.any { matches(waypoint, it.latitude, it.longitude) }
                verify()
            }
        } }
        override fun onError(errorCode: NaviErrorCode) { main.post { finish("failed", "내비 오류: $errorCode") } }
    }

    init {
        runCatching {
            sdk.initialize(onConnected = {
                main.post {
                    if (!closed) {
                        runCatching { sdk.addListener(listener) }.onSuccess {
                            connected = true
                            onStatus("내비게이션 연결됨")
                        }.onFailure { onStatus("내비 이벤트 등록 실패: ${it.message}") }
                    }
                }
            }, onFailed = { error -> main.post { onStatus("내비 연결 실패: ${error.message}") } })
        }.onFailure { onStatus("내비 초기화 실패: ${it.message}") }
    }

    fun apply(destination: JSONObject, waypoint: JSONObject, result: (String, String) -> Unit) {
        check(onResult == null) { "이전 내비 요청을 확인 중입니다." }
        if (!connected) { result("failed", "내비게이션 서비스가 연결되지 않았습니다."); return }
        this.destination = destination
        this.waypoint = waypoint
        completed = false
        destinationMatches = false
        waypointMatches = false
        onResult = result
        main.postDelayed(timeout, 45000)
        runCatching {
            sdk.requestRouteWithWaypoints(RouteWithWaypointsRequest(
                destination = RouteInfo(latitude = destination.getDouble("latitude"), longitude = destination.getDouble("longitude"),
                    poiName = destination.getString("name"), poiId = destination.optString("poi_id"),
                    address = destination.optString("address"), poiSubId = ""),
                waypoints = listOf(RequestWaypointInfo(latitude = waypoint.getDouble("latitude"), longitude = waypoint.getDouble("longitude"),
                    poiName = waypoint.getString("name"), waypointIndex = WaypointIndex.FIRST,
                    poiId = waypoint.optString("poi_id"), address = waypoint.optString("address"), poiSubId = ""))
            ))
            onStatus("경로 요청 전송 · 목적지와 경유지 반영을 확인 중")
        }.onFailure { finish("failed", "경로 요청 실패: ${it.message}") }
    }

    private fun verify() {
        if (completed && destinationMatches && waypointMatches) finish("succeeded", "SDK 경로 완료 및 목적지·경유지 좌표 확인")
    }

    private fun finish(state: String, detail: String) {
        val callback = onResult ?: return
        onResult = null
        main.removeCallbacks(timeout)
        callback(state, detail)
    }

    fun close() {
        closed = true
        finish("unconfirmed", "앱 종료로 경로 반영 확인이 중단되었습니다.")
        runCatching { sdk.removeListener(listener) }
        runCatching { sdk.release() }
    }
}
