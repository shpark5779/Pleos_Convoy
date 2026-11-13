package com.example.pleosprojectv01

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import com.skt.tmap.vsm.data.VSMMapPoint
import com.skt.tmap.vsm.camera.CameraUpdateFactory
import com.skt.tmap.vsm.camera.CameraPosition
import com.skt.tmap.vsm.map.MapEngine
import com.skt.tmap.vsm.map.marker.MarkerImage
import com.skt.tmap.vsm.map.marker.VSMMarkerPoint
import org.json.JSONObject
import java.util.concurrent.Executors
import java.text.DateFormat
import java.util.Date

/** Only the explicit map-preview button moves the camera once; never requests routes. */
class NativeFuelLayer(private val activity: Activity, private val map: () -> MapEngine?) {
    private val io=Executors.newSingleThreadExecutor()
    private val ids=mutableSetOf<String>()
    private var busy=false
    private fun request(body: JSONObject, done:(JSONObject)->Unit) {
        if(busy)return
        busy=true
        val p=activity.getSharedPreferences("convoy",Activity.MODE_PRIVATE)
        val session=ConvoySession(p.getString("server","")!!,p.getString("code","")!!,
            p.getString("member_id","")!!,p.getString("token","")!!)
        io.execute {
            val result=runCatching { ConvoyApi.room(session,"fuel",body) }
            activity.runOnUiThread {
                busy=false
                if(activity.isDestroyed)return@runOnUiThread
                result.onSuccess(done).onFailure {
                    AlertDialog.Builder(activity).setTitle("주유소 가격 조회").setMessage(it.message)
                        .setPositiveButton("확인",null).show()
                }
            }
        }
    }
    fun show() {
        AlertDialog.Builder(activity).setTitle("주변 5km · 오피넷 가격")
            .setItems(arrayOf("휘발유", "경유", "가격 마커 숨기기")) { _, which ->
                clear()
                if(which!=2)load(if(which==0)"B027" else "D047")
            }.show()
    }
    private fun clear() { ids.forEach { map()?.markerManager?.removeMarker(it) };ids.clear() }
    private fun load(product:String) = request(JSONObject().put("product",product)) { data ->
        val manager=map()?.markerManager ?: return@request
        val rows=data.getJSONArray("stations")
        clear()
        val labels=Array(rows.length()) { i ->
            val s=rows.getJSONObject(i);val price=s.getDouble("price").toInt()
            val bitmap=Bitmap.createBitmap(164,82,Bitmap.Config.ARGB_8888)
            val canvas=Canvas(bitmap);val paint=Paint(Paint.ANTI_ALIAS_FLAG)
            paint.color=Color.rgb(0,100,135);canvas.drawRoundRect(0f,0f,164f,82f,14f,14f,paint)
            paint.color=Color.WHITE;paint.textAlign=Paint.Align.CENTER;paint.textSize=18f
            canvas.drawText(if(product=="B027")"휘발유" else "경유",82f,24f,paint)
            paint.textSize=28f;canvas.drawText("${price}원/L",82f,62f,paint)
            val id="fuel-${s.getString("id")}"
            manager.addMarker(VSMMarkerPoint(id).apply {
                position=VSMMapPoint(s.getDouble("longitude"),s.getDouble("latitude"))
                icon=MarkerImage.fromBitmap(bitmap);text=s.getString("name")
            });ids.add(id)
            "${s.getString("name")} · ${price}원/L"
        }
        val fetched=DateFormat.getTimeInstance(DateFormat.SHORT).format(Date((data.getDouble("fetched_at")*1000).toLong()))
        AlertDialog.Builder(activity).setTitle("${if(product=="B027")"휘발유" else "경유"} · ${labels.size}곳 · 조회 $fetched")
            .setItems(labels) { _, i -> detail(rows.getJSONObject(i).getString("id")) }
            .setMessage(if(labels.isEmpty())"주변 판매가격 정보가 없습니다." else null)
            .setNegativeButton("지도에서 보기") { _, _ ->
                if(rows.length()>0) {
                    val points=(0 until rows.length()).map { rows.getJSONObject(it) }
                    val center=VSMMapPoint(points.map { it.getDouble("longitude") }.average(),
                        points.map { it.getDouble("latitude") }.average())
                    map()?.moveCamera(CameraUpdateFactory.newCameraPosition(
                        CameraPosition.Builder().target(center).zoom(12.5).tilt(0f).bearing(0f).build()))
                }
            }.show()
    }
    private fun detail(id:String) = request(JSONObject().put("action","detail").put("id",id)) { data ->
        val rows=data.getJSONArray("prices")
        val text=(0 until rows.length()).joinToString("\n") {
            val p=rows.getJSONObject(it)
            "${p.getString("product_name")}: ${if(p.isNull("price"))"미확인" else "${p.getDouble("price").toInt()}원/L"}\n기준 ${p.optString("date")} ${p.optString("time")}"
        }
        AlertDialog.Builder(activity).setTitle(data.getString("name"))
            .setMessage("${data.getString("address")}\n\n$text\n\n한국석유공사 오피넷 · 실제 가격/영업 여부는 현장 확인")
            .setPositiveButton("확인",null).show()
    }
    fun close() { clear();io.shutdown() }
}
