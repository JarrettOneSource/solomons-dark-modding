void ProcessCompletedHostLootPickups() {
    SDModHostLootDropDeactivationResult deactivation;
    while (sdmod::TryTakeHostLootDropDeactivationResult(&deactivation)) {
        const auto pending_it =
            g_local_transport.pending_host_loot_pickups_by_drop_id.find(
                deactivation.network_drop_id);
        if (pending_it ==
            g_local_transport.pending_host_loot_pickups_by_drop_id.end()) {
            Log(
                "Multiplayer discarded an orphaned host loot deactivation result. "
                "network_drop_id=" + std::to_string(deactivation.network_drop_id));
            continue;
        }
        PendingHostLootPickup pending = std::move(pending_it->second);
        g_local_transport.pending_host_loot_pickups_by_drop_id.erase(pending_it);
        FinalizeHostLootPickup(std::move(pending), deactivation);
    }
}
