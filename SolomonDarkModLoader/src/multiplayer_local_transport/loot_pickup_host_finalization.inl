void FinalizeHostLootPickup(
    PendingHostLootPickup pending,
    const SDModHostLootDropDeactivationResult& deactivation) {
    const bool deactivated =
        deactivation.deactivated &&
        deactivation.run_nonce == pending.packet.run_nonce &&
        deactivation.network_drop_id == pending.packet.network_drop_id &&
        deactivation.actor_address == pending.actor_address &&
        deactivation.drop_kind == pending.drop_kind;

    bool reward_applied = deactivated;
    std::string powerup_apply_error;
    if (deactivated &&
        pending.drop_kind == LootDropKind::Powerup) {
        reward_applied = TryApplyPreparedPowerupReward(
            &pending,
            &powerup_apply_error);
    }

    if (deactivated) {
        g_local_transport.accepted_loot_pickup_drop_ids.insert(
            pending.packet.network_drop_id);
    }
    if (reward_applied) {
        ApplyAcceptedHostLootPickupState(&pending);
    }

    LootPickupResultPayload result_payload = pending.payload;
    if (!reward_applied) {
        const auto runtime_state = SnapshotRuntimeState();
        result_payload = BuildLootPickupResultPayloadFromParticipant(
            pending.host_self
                ? FindLocalParticipant(runtime_state)
                : FindParticipant(
                      runtime_state,
                      pending.packet.participant_id));
    }
    SendLootPickupResult(
        pending.packet,
        pending.endpoint,
        reward_applied
            ? LootPickupResultCode::Accepted
            : LootPickupResultCode::Rejected,
        pending.drop_kind,
        result_payload,
        pending.host_self);

    Log(
        "Multiplayer loot pickup " +
        std::string(reward_applied ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(pending.packet.participant_id) +
        " network_drop_id=" + std::to_string(pending.packet.network_drop_id) +
        " kind=" + LootDropKindLabel(pending.drop_kind) +
        " amount=" + std::to_string(deactivated ? result_payload.amount : 0) +
        " resulting_gold=" + std::to_string(result_payload.resulting_gold) +
        " gold_revision=" + std::to_string(result_payload.gold_revision) +
        " resource_kind=" + std::to_string(result_payload.resource_kind) +
        " resource_delta=" +
            std::to_string(deactivated ? result_payload.resource_delta : 0.0f) +
        " resulting_life=" + std::to_string(result_payload.resulting_life_current) + "/" +
        std::to_string(result_payload.resulting_life_max) +
        " resulting_mana=" + std::to_string(result_payload.resulting_mana_current) + "/" +
        std::to_string(result_payload.resulting_mana_max) +
        " item_type_id=" +
            HexString(static_cast<uintptr_t>(result_payload.item_type_id)) +
        " item_recipe_uid=" + std::to_string(result_payload.item_recipe_uid) +
        " item_slot=" + std::to_string(result_payload.item_slot) +
        " stack_count=" + std::to_string(result_payload.stack_count) +
        " inventory_revision=" + std::to_string(result_payload.inventory_revision) +
        " powerup_kind=" +
            std::to_string(
                static_cast<std::int32_t>(
                    result_payload.powerup_kind)) +
        " powerup_skill_entry_index=" +
            std::to_string(
                result_payload.powerup_skill_entry_index) +
        " powerup_skill_resulting_active=" +
            std::to_string(
                result_payload.powerup_skill_resulting_active) +
        " damage_x4_remaining_ticks=" +
            std::to_string(
                result_payload.damage_x4_remaining_ticks) +
        " deactivated=" + std::to_string(deactivated ? 1 : 0) +
        (powerup_apply_error.empty()
             ? ""
             : " powerup_error=" + powerup_apply_error) +
        " gameplay_thread=1" +
        " seh=" + HexString(static_cast<uintptr_t>(deactivation.exception_code)));
}
