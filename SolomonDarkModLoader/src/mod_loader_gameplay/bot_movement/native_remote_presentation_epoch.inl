bool BindNativeRemoteParticipantPresentationEpoch(
    ParticipantEntityBinding* binding,
    const multiplayer::ParticipantTransformSample& transform_sample) {
    if (binding == nullptr ||
        transform_sample.presentation_scene_epoch == 0) {
        return false;
    }

    if (binding->replicated_presentation_scene_epoch !=
        transform_sample.presentation_scene_epoch) {
        ResetParticipantEntityActorPresentationState(binding);
        binding->replicated_presentation_scene_epoch =
            transform_sample.presentation_scene_epoch;
    }
    return binding->materialized_presentation_scene_epoch ==
        transform_sample.presentation_scene_epoch;
}
