using System.Diagnostics;
using System.Threading.Tasks;
using UnityEngine;
using Debug = UnityEngine.Debug;

public class AnchorPlacementScript : MonoBehaviour
{
    public GameObject prefabToPlace;
    public Transform placementHand; // RightControllerAnchor

    void Update()
    {
        // Trigger with 'A' button on Right Controller
        if (OVRInput.GetDown(OVRInput.Button.One))
        {
            PlaceAndSaveAnchor();
        }
    }

    // Using 'async void' for the top-level button event
    private async void PlaceAndSaveAnchor()
    {
        // 1. Instantiate the object
        GameObject spawnedObject = Instantiate(prefabToPlace, placementHand.position, placementHand.rotation);

        // 2. Add the component
        var anchor = spawnedObject.AddComponent<OVRSpatialAnchor>();

        // 3. Wait for the Quest to finish creating/localizing the anchor in the room
        // This replaces the old 'while(!anchor.Created)' loop
        bool localized = await anchor.WhenLocalizedAsync();

        if (localized)
        {
            Debug.Log("Anchor localized! Now saving...");

            // 4. Use the new SaveAnchorAsync method (The fix for your warning)
            var result = await anchor.SaveAnchorAsync();

            if (result.Success)
            {
                Debug.Log($"Success! Anchor saved with UUID: {anchor.Uuid}");
            }
            else
            {
                Debug.LogError("Failed to save anchor.");
            }
        }
    }
}