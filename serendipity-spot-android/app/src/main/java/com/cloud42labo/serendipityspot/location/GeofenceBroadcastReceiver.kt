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
        if (intent.action != ACTION_GEOFENCE_EVENT) return

        val geofencingEvent = GeofencingEvent.fromIntent(intent) ?: return
        if (geofencingEvent.hasError()) return
        if (geofencingEvent.geofenceTransition != Geofence.GEOFENCE_TRANSITION_ENTER) return

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
