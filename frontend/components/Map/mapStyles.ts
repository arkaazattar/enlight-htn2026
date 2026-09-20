type MapPalette = {
    geometry: string;
    labels: string;
    labelStroke: string;
    administrative: string;
    natural: string;
    park: string;
    parkLabels: string;
    road: string;
    arterial: string;
    highway: string;
    highwayStroke: string;
    controlledAccess: string;
    controlledAccessStroke: string;
    water: string;
};

function createMapStyles(colors: MapPalette): google.maps.MapTypeStyle[] {
    return [
        { elementType: 'geometry', stylers: [{ color: colors.geometry }] },
        { elementType: 'labels.text.fill', stylers: [{ color: colors.labels }] },
        { elementType: 'labels.text.stroke', stylers: [{ color: colors.labelStroke }] },
        { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: colors.administrative }] },
        { featureType: 'administrative.land_parcel', stylers: [{ visibility: 'off' }] },
        { featureType: 'administrative.neighborhood', stylers: [{ visibility: 'off' }] },
        { featureType: 'landscape.natural', elementType: 'geometry', stylers: [{ color: colors.natural }] },
        { featureType: 'poi', elementType: 'geometry', stylers: [{ color: colors.natural }] },
        { featureType: 'poi', elementType: 'labels.text', stylers: [{ visibility: 'off' }] },
        { featureType: 'poi.business', stylers: [{ visibility: 'off' }] },
        { featureType: 'poi.park', elementType: 'geometry.fill', stylers: [{ color: colors.park }] },
        { featureType: 'poi.park', elementType: 'labels.text.fill', stylers: [{ color: colors.parkLabels }] },
        { featureType: 'road', elementType: 'geometry', stylers: [{ color: colors.road }] },
        { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
        { featureType: 'road.arterial', elementType: 'geometry', stylers: [{ color: colors.arterial }] },
        { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: colors.highway }] },
        { featureType: 'road.highway', elementType: 'geometry.stroke', stylers: [{ color: colors.highwayStroke }] },
        { featureType: 'road.highway.controlled_access', elementType: 'geometry', stylers: [{ color: colors.controlledAccess }] },
        { featureType: 'road.highway.controlled_access', elementType: 'geometry.stroke', stylers: [{ color: colors.controlledAccessStroke }] },
        { featureType: 'road.local', stylers: [{ visibility: 'off' }] },
        { featureType: 'transit', stylers: [{ visibility: 'off' }] },
        { featureType: 'water', elementType: 'geometry.fill', stylers: [{ color: colors.water }] },
        { featureType: 'water', elementType: 'labels.text', stylers: [{ visibility: 'off' }] },
    ];
}

export const lightMapStyles = createMapStyles({
    geometry: '#f6e9df',
    labels: '#3d4741',
    labelStroke: '#fff8f2',
    administrative: '#cfb8aa',
    natural: '#dfe5ce',
    park: '#abc59c',
    parkLabels: '#315d3d',
    road: '#fff8f1',
    arterial: '#ffffff',
    highway: '#f5c47d',
    highwayStroke: '#e4ad65',
    controlledAccess: '#e99e78',
    controlledAccessStroke: '#d98c6b',
    water: '#afd5d4',
});

export const darkMapStyles = createMapStyles({
    geometry: '#242a29',
    labels: '#d5ddda',
    labelStroke: '#1a2221',
    administrative: '#59625e',
    natural: '#303d35',
    park: '#3e624b',
    parkLabels: '#b5d2b5',
    road: '#3d4543',
    arterial: '#505957',
    highway: '#967a50',
    highwayStroke: '#745d3f',
    controlledAccess: '#a36651',
    controlledAccessStroke: '#7e4d40',
    water: '#214751',
});
