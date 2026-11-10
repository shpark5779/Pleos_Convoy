package com.example.pleosprojectv01

import android.content.Intent
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference
import android.graphics.Bitmap
import java.io.File

/** Explicit two-device check of the real WebView, SDK GPS and TMAP JS map. */
class JourneyMapTest {
    @Test fun bothOriginsAppearOnTmap() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("tmap_map") == "true")
        val i = InstrumentationRegistry.getInstrumentation()
        val activity = i.startActivitySync(Intent(i.targetContext, JourneyActivity::class.java)
            .putExtra("share_location", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        val web = (activity.findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as WebView)
        fun js(code: String): String {
            val value = AtomicReference<String?>(null)
            i.runOnMainSync { web.evaluateJavascript(code) { value.set(it) } }
            val deadline = System.currentTimeMillis()+5000
            while (value.get() == null && System.currentTimeMillis()<deadline) Thread.sleep(50)
            return value.get().orEmpty()
        }
        fun await(predicate: () -> Boolean) {
            val end = System.currentTimeMillis()+60000
            while (System.currentTimeMillis()<end) { if(predicate()) return; Thread.sleep(500) }
            throw AssertionError(js("document.body.innerText"))
        }
        await { js("document.getElementById('mapStatus')?.textContent").contains("TMAP 지도 ·") }
        await { val text=js("document.getElementById('members')?.textContent")
            text.contains("37.56650") && text.contains("36.35040") && !text.contains("오래된 위치") }
        js("document.getElementById('refresh').click()")
        await { val text=js("document.getElementById('summary')?.textContent")
            text.contains("Emulator A") && text.contains("Emulator B") }
        assertTrue(js("document.getElementById('mapStatus').textContent").contains("TMAP 지도 ·"))
        Thread.sleep(1200) // Let map tiles finish painting before retaining visual evidence.
        File(i.targetContext.filesDir, "tmap-map.png").outputStream().use {
            i.uiAutomation.takeScreenshot().compress(Bitmap.CompressFormat.PNG, 100, it)
        }
    }
}
