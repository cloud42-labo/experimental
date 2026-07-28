package com.cloud42labo.serendipityspot.location

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import com.cloud42labo.serendipityspot.data.Spot
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingClient
import com.google.android.gms.location.GeofencingRequest
import com.google.android.gms.location.LocationServices
import kotlinx.coroutines.tasks.await

/**
 * スポット一覧をもとに端末のジオフェンスを張り直す。
 * Android/Google Playの上限（1アプリ100件）があるため、多すぎる場合は
 * 直近に追加したものを優先して先頭100件に絞る。
 */
class GeofenceHelper(private val context: Context) {

    private val geofencingClient: GeofencingClient = LocationServices.getGeofencingClient(context)

    private val pendingIntent: PendingIntent by lazy {
        val intent = Intent(context, GeofenceBroadcastReceiver::class.java).apply {
            action = GeofenceBroadcastReceiver.ACTION_GEOFENCE_EVENT
        }
        PendingIntent.getBroadcast(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        )
    }

    @SuppressLint("MissingPermission")
    suspend fun resync(spots: List<Spot>) {
        geofencingClient.removeGeofences(pendingIntent).await()
        if (spots.isEmpty()) return

        val targets = spots.take(MAX_GEOFENCES)
        val geofences = targets.map { spot ->
            Geofence.Builder()
                .setRequestId(spot.id)
                .setCircularRegion(spot.lat, spot.lng, spot.radiusMeters)
                .setExpirationDuration(Geofence.NEVER_EXPIRE)
                .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_ENTER)
                .setLoiteringDelay(0)
                .build()
        }

        val request = GeofencingRequest.Builder()
            .setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
            .addGeofences(geofences)
            .build()

        geofencingClient.addGeofences(request, pendingIntent).await()
    }

    companion object {
        private const val MAX_GEOFENCES = 100
    }
}
