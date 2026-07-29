package com.cloud42labo.serendipityspot.location

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.cloud42labo.serendipityspot.data.SpotLocalCache
import com.cloud42labo.serendipityspot.notification.NotificationHelper
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingEvent

/**
 * システムからジオフェンス到達イベントを受け取る。
 * アプリがバックグラウンド/終了状態でも呼ばれるため、ここでは
 * ローカルキャッシュ（スプレッドシートの最新コピー）だけを参照して通知する。
 * ネットワークやサインイン状態には依存しない。
 */
class GeofenceBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        // 何を受け取ったかは、握りつぶす場合も含めて必ず残す。
        // 「イベント自体が来ていない」のか「来ているが弾いている」のかを
        // 端末だけで切り分けられるようにするため。
        if (intent.action != ACTION_GEOFENCE_EVENT) {
            SpotLocalCache.saveLastGeofenceEvent(context, "別のaction: ${intent.action}")
            return
        }

        val geofencingEvent = GeofencingEvent.fromIntent(intent)
        if (geofencingEvent == null) {
            SpotLocalCache.saveLastGeofenceEvent(context, "中身を取り出せず")
            return
        }
        if (geofencingEvent.hasError()) {
            SpotLocalCache.saveLastGeofenceEvent(context, "エラー code=${geofencingEvent.errorCode}")
            return
        }

        val transition = geofencingEvent.geofenceTransition
        val ids = geofencingEvent.triggeringGeofences?.size ?: 0
        SpotLocalCache.saveLastGeofenceEvent(context, "transition=$transition 対象=${ids}件")

        if (transition != Geofence.GEOFENCE_TRANSITION_ENTER) return

        NotificationHelper.ensureChannel(context)
        val cachedSpots = SpotLocalCache.load(context).associateBy { it.id }

        geofencingEvent.triggeringGeofences?.forEach { geofence ->
            val spot = cachedSpots[geofence.requestId] ?: return@forEach
            NotificationHelper.notifyNearby(context, spot)
        }
    }

    companion object {
        const val ACTION_GEOFENCE_EVENT = "com.cloud42labo.serendipityspot.ACTION_GEOFENCE_EVENT"
    }
}
