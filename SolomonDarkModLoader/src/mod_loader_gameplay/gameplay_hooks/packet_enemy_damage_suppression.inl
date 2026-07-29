bool ShouldSuppressPacketDrivenRemoteReplicatedEnemyDamage(
    uintptr_t target_actor_address,
    uintptr_t source_actor_address) {
    if (!multiplayer::IsLocalTransportEnabled() ||
        target_actor_address == 0 ||
        source_actor_address == 0 ||
        multiplayer::GetLocalRunEnemyNetworkActorId(
            target_actor_address) == 0) {
        return false;
    }
    const auto source_participant_id =
        ResolveDamageSourceParticipantId(source_actor_address);
    const auto local_participant_id =
        multiplayer::GetLocalTransportParticipantId();
    if (source_participant_id == 0 ||
        local_participant_id == 0 ||
        source_participant_id == local_participant_id) {
        return false;
    }
    std::lock_guard<std::recursive_mutex> lock(
        g_participant_entities_mutex);
    const auto* binding =
        FindParticipantEntity(source_participant_id);
    if (!IsPacketDrivenRemoteParticipantBinding(binding)) {
        return false;
    }
    return true;
}
