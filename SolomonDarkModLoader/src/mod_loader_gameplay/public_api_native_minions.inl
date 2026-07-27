void RetireAuthoritativeNativeMinionsForLocalOwnerDeath() {
    RetireAuthoritativeNativeMinionsForOwner(
        multiplayer::GetLocalTransportParticipantId(),
        NativeMinionTerminalReason::OwnerDeath);
}
