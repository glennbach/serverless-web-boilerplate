package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
)

var (
	// errNoUser means the request does not identify a current user (401).
	errNoUser = errors.New("no current user")
	// errBadMode means AUTH_MODE is not "dev" or "aws" (500).
	errBadMode = errors.New("AUTH_MODE must be dev or aws")
)

// currentEmail returns the current user's email for the given AUTH_MODE.
func currentEmail(authMode string, r *http.Request) (string, error) {
	switch authMode {
	case "dev":
		return "dev@localhost", nil
	case "aws":
		// The Lambda Web Adapter sets this header from the API Gateway
		// request context, replacing any copy the client sent.
		var rc struct {
			Authorizer struct {
				JWT struct {
					Claims struct {
						Email string `json:"email"`
					} `json:"claims"`
				} `json:"jwt"`
			} `json:"authorizer"`
		}
		if err := json.Unmarshal([]byte(r.Header.Get("x-amzn-request-context")), &rc); err != nil {
			return "", fmt.Errorf("%w: unreadable request context", errNoUser)
		}
		if email := rc.Authorizer.JWT.Claims.Email; email != "" {
			return email, nil
		}
		return "", fmt.Errorf("%w: no email claim", errNoUser)
	default:
		return "", errBadMode
	}
}
