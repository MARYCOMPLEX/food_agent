{
  "manifestVersion": "domain-pack-manifest/v1",
  "domainId": "food",
  "packVersion": "1.0.0",
  "contractApi": "domain-contract/v1",
  "coreVersionRange": ">=1.0.0,<2.0.0",
  "manifestDigest": "b0787e4c23f92d9d64564dd480a0f17a59713a740e6fe14ed200264c5a8679de",
  "methods": [
    "describe",
    "classify_constraints",
    "validate_evidence",
    "compute_features",
    "score_public",
    "build_final_output",
    "map_error"
  ],
  "domainSchemas": {
    "entities": "urn:food-agent:food:entities:v1",
    "relations": "urn:food-agent:food:relations:v1",
    "evidenceTypes": "urn:food-agent:food:evidence-types:v1",
    "featureSet": "urn:food-agent:food:feature-set:v1",
    "personalizationSlots": "urn:food-agent:food:personalization-slots:v1"
  },
  "methodSchemas": [
    {
      "method": "describe",
      "inputSchemaId": "urn:food-agent:domain-method:describe-input:v1",
      "inputSchemaDigest": "c67a3ef58bea90053d76251c9f9b7d72513a473ac3b493a776f871b694ebdc4c",
      "outputSchemaId": "urn:food-agent:domain-pack-manifest:v1",
      "outputSchemaDigest": "cf18f7372cdf8cc103748c7a39e72258810a910db4a70783b7facf52335eb29c"
    },
    {
      "method": "classify_constraints",
      "inputSchemaId": "urn:food-agent:domain-method:classify-constraints-input:v1",
      "inputSchemaDigest": "019cdb9754bdbf064e03cf206d7584f3269b3e59e3b627ee84e661cbcaaae0a9",
      "outputSchemaId": "urn:food-agent:domain-method:classify-constraints-output:v1",
      "outputSchemaDigest": "483114a40fb6d8469fa36edabab3de30c1afe5a9f99365f43e4cdcfeea48a75e"
    },
    {
      "method": "validate_evidence",
      "inputSchemaId": "urn:food-agent:domain-method:validate-evidence-input:v1",
      "inputSchemaDigest": "282060148fe54aff339d706de15f6296db479a051450a6700c53666808e793f2",
      "outputSchemaId": "urn:food-agent:domain-method:validate-evidence-output:v1",
      "outputSchemaDigest": "651bb0bda11b0b60bbba677b7ed8a5267f81883ad781b80074d00806a49590e4"
    },
    {
      "method": "compute_features",
      "inputSchemaId": "urn:food-agent:domain-method:compute-features-input:v1",
      "inputSchemaDigest": "7eef327d351a18492f10c0f04352f059de7d4b4ee877954a8d810023f15598c9",
      "outputSchemaId": "urn:food-agent:domain-method:compute-features-output:v1",
      "outputSchemaDigest": "1c54963e6e3b7ab68227c85316ebac54562cac12858f1c5cb5f342ee0b382f86"
    },
    {
      "method": "score_public",
      "inputSchemaId": "urn:food-agent:domain-method:score-public-input:v1",
      "inputSchemaDigest": "b693f9a6beb436169d5dc5bb909a36a09bd4d3417b9db1baa73318e0b273c4fc",
      "outputSchemaId": "urn:food-agent:domain-method:score-public-output:v1",
      "outputSchemaDigest": "ca3e9da31b4c2dcbcc22f50a55fd638c1fc6ab0c51935aa8f01c566e9746c664"
    },
    {
      "method": "build_final_output",
      "inputSchemaId": "urn:food-agent:domain-method:build-final-output-input:v1",
      "inputSchemaDigest": "6af85cf0fe2403472b0e134dafcedb00784568be90db7fc08e6d4fb5e57e7737",
      "outputSchemaId": "urn:food-agent:domain-method:build-final-output-output:v1",
      "outputSchemaDigest": "9c034f3eff03c535891876717eaa18e8cb91c4341720d3bb482d987bb461e78e"
    },
    {
      "method": "map_error",
      "inputSchemaId": "urn:food-agent:domain-method:map-error-input:v1",
      "inputSchemaDigest": "01ae2d7e4ec811204bf099839eb4e9f670981e7892e9a2bff3a5948474d8a674",
      "outputSchemaId": "urn:food-agent:stable-error:v1",
      "outputSchemaDigest": "d5f01b2f63a02aba36561c5a9248ca65f60c6cb73fcbc7deff6acb8c4fad6e51"
    }
  ],
  "allowedTools": [],
  "finalOutputSchemaDigest": "2b5334db461f1c7b6dc831f94a4fc85bb228c471a14f83f3038d4fd2de1fb2c7",
  "finalOutputSchema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:food-agent:food:agent-final-output:v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "summary",
      "recommendations"
    ],
    "properties": {
      "schemaVersion": {
        "const": "food-agent-final-output/v1"
      },
      "summary": {
        "type": "string"
      },
      "recommendations": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "entityId",
            "publicScore",
            "explanationRefs"
          ],
          "properties": {
            "entityId": {
              "type": "string",
              "minLength": 1
            },
            "publicScore": {
              "type": "number",
              "minimum": 0,
              "maximum": 1
            },
            "explanationRefs": {
              "type": "array",
              "items": {
                "type": "string"
              }
            }
          }
        }
      }
    }
  },
  "finalOutputExample": {
    "schemaVersion": "food-agent-final-output/v1",
    "summary": "找到 1 个公共候选。",
    "recommendations": [
      {
        "entityId": "restaurant-001",
        "publicScore": 0.91,
        "explanationRefs": [
          "evidence-001"
        ]
      }
    ]
  },
  "scoringPolicy": {
    "policyId": "food.public-score",
    "policyVersion": "1.0.0",
    "mode": "pure_deterministic",
    "inputs": [
      "declared_public_feature_set",
      "explicit_versioned_config"
    ],
    "forbiddenInputs": [
      "user_memory",
      "session_memory",
      "wall_clock",
      "randomness",
      "environment",
      "framework_state"
    ],
    "forbiddenEffects": [
      "network",
      "filesystem",
      "database",
      "cache",
      "workflow",
      "connector"
    ]
  },
  "domainSources": [
    {
      "capability": "notes.search",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    },
    {
      "capability": "notes.detail",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    },
    {
      "capability": "comments.search",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    },
    {
      "capability": "places.search",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    },
    {
      "capability": "places.detail",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    },
    {
      "capability": "reviews.search",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": false
    }
  ],
  "policyProfiles": {
    "workflow": "research-standard/v1",
    "freshness": "food-freshness/v1",
    "coverage": "food-coverage/v1",
    "stopping": "food-stopping/v1",
    "refreshJob": "food-refresh-declaration/v1"
  }
}
